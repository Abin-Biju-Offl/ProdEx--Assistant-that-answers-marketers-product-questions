"""Retrieve -> threshold -> generate -> validate -> log (spec section 10).

This module is the whole answer path. Every branch that decides "not in the docs"
goes through `_refuse`, so the refusal reason is always recorded in the log.
"""

from __future__ import annotations

import logging
import re
import time

from app.config import settings
from app.generation.llm import LLM, LLMUnavailable, get_llm
from app.generation.prompts import (
    NOT_IN_DOCS,
    NOT_IN_DOCS_MESSAGE,
    PROMPT_VERSION,
    build_messages,
)
from app.logging_ import store
from app.models import AskRequest, AskResponse, Source
from app.retrieval.filters import normalize_levels
from app.retrieval.search import hybrid_search, rerank

log = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def normalize_question(question: str) -> str:
    """Trim and collapse whitespace - also the answer-cache key input (spec 10.1)."""
    return re.sub(r"\s+", " ", question or "").strip()


def clean_answer(text: str) -> str:
    """Trim the wrappers small models add around the actual answer."""
    cleaned = (text or "").strip()
    for prefix in ("Answer:", "A:", "Assistant:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned


def is_refusal(answer: str) -> bool:
    return answer.strip().upper().startswith(NOT_IN_DOCS)


def valid_citations(answer: str, passage_count: int) -> bool:
    """At least one [n] marker that maps to a passage we actually supplied."""
    markers = {int(m) for m in _CITATION_RE.findall(answer)}
    return any(1 <= m <= passage_count for m in markers)


def build_sources(chunks: list[dict]) -> list[Source]:
    sources = []
    for i, chunk in enumerate(chunks, start=1):
        updated = chunk.get("updated_at")
        sources.append(
            Source(
                n=i,
                title=" > ".join(
                    p for p in (chunk.get("repo"), chunk.get("path"), chunk.get("heading_path")) if p
                ),
                url=chunk.get("url", ""),
                updated_at=updated.strftime("%Y-%m-%d") if hasattr(updated, "strftime") else None,
            )
        )
    return sources


def _docs_as_of() -> str:
    version = store.docs_version()
    return version.split("T")[0] if version != "empty" else None


def answer_question(request: AskRequest, llm: LLM | None = None, use_cache: bool = True) -> AskResponse:
    started = time.perf_counter()
    question = normalize_question(request.question)
    levels = normalize_levels(request.access_levels)
    version = store.docs_version()
    model_name = settings.llm_model

    # 1. cache (keyed on the normalised question + docs version, so any re-ingest
    #    invalidates every cached answer)
    payload = store.cache_get(store.cache_key(question, version)) if (levels and use_cache) else None
    if payload:
        chunk_ids = payload.pop("chunk_ids", [])
        request_id = store.log_request(
            slack_user_id=request.slack_user_id,
            channel_type=request.channel_type,
            question=question,
            answer=payload["answer"],
            answered=payload["answered"],
            top_score=payload.get("confidence"),
            chunk_ids=chunk_ids,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=model_name,
            cached=True,
        )
        return AskResponse(request_id=request_id, cached=True, **payload)

    if not levels:
        # fail closed: no permitted access level means no retrieval
        return _refuse(request, question, started, model_name, reason="no-access-level")

    # 2-4. hybrid search, boosts
    candidates = hybrid_search(question, levels, settings.top_k_retrieve)

    # 5. rerank down to the final context size
    top = rerank(question, candidates, settings.top_k_final)
    if not top:
        return _refuse(request, question, started, model_name, reason="no-candidates")

    # 6. threshold: below MIN_RERANK_SCORE we do not call the LLM at all
    best = top[0]["rerank_score"]
    if best < settings.min_rerank_score:
        log.info("below threshold (%.3f < %.3f)", best, settings.min_rerank_score)
        return _refuse(request, question, started, model_name, reason="below-threshold",
                       chunks=top, top_score=best)

    # 7. generate
    llm = llm or get_llm()
    try:
        raw = llm.chat(build_messages(question, top))
    except LLMUnavailable as exc:
        log.error("LLM unavailable: %s", exc)
        return _refuse(request, question, started, model_name, reason="llm-unavailable",
                       chunks=top, top_score=best)

    # 8. validate: refusals and uncited answers are both "not in the docs"
    raw = clean_answer(raw)
    if is_refusal(raw) or not valid_citations(raw, len(top)):
        log.info("model output rejected (refusal=%s citations=%s)", is_refusal(raw),
                 valid_citations(raw, len(top)))
        return _refuse(request, question, started, model_name, reason="unvalidated",
                       chunks=top, top_score=best)

    response = AskResponse(
        request_id=0,  # replaced below, once we have the log row id
        answered=True,
        answer=raw,
        sources=build_sources(top),
        confidence=round(float(best), 4),
        docs_as_of=_docs_as_of(),
    )
    payload = response.model_dump(exclude={"request_id", "cached"})
    payload["chunk_ids"] = [c["id"] for c in top]
    store.cache_put(store.cache_key(question, version), question, version, payload)

    response.request_id = store.log_request(
        slack_user_id=request.slack_user_id,
        channel_type=request.channel_type,
        question=question,
        answer=response.answer,
        answered=True,
        top_score=response.confidence,
        chunk_ids=[c["id"] for c in top],
        latency_ms=int((time.perf_counter() - started) * 1000),
        model=model_name,
    )
    return response


def _refuse(
    request: AskRequest,
    question: str,
    started: float,
    model_name: str,
    *,
    reason: str,
    chunks: list[dict] | None = None,
    top_score: float | None = None,
) -> AskResponse:
    message = NOT_IN_DOCS_MESSAGE.format(owner_hint=settings.owner_hint)
    log.info(
        "not in the docs (%s) prompt=%s q=%r", reason, PROMPT_VERSION, question[:80]
    )
    return AskResponse(
        request_id=store.log_request(
            slack_user_id=request.slack_user_id,
            channel_type=request.channel_type,
            question=question,
            answer=message,
            answered=False,
            top_score=top_score,
            chunk_ids=[c["id"] for c in (chunks or [])],
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=model_name,
        ),
        answered=False,
        answer=message,
        sources=build_sources(chunks) if chunks else [],
        confidence=None,
        docs_as_of=_docs_as_of(),
        owner_hint=settings.owner_hint,
    )