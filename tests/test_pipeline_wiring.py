"""End-to-end wiring test with the database and models stubbed out.

Proves the whole path works together - collect, chunk, prompt, validate, answer,
log - without Postgres, a network or a model. Run locally with:
    python -m pytest tests/test_pipeline_wiring.py
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config import settings
from app.generation import answer as answer_module
from app.generation.answer import answer_question
from app.ingestion import mock_source
from app.ingestion.pipeline import chunk_document
from app.models import AskRequest

NOW = datetime(2026, 10, 12, tzinfo=UTC)


class _StubLLM:
    name = "stub"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict]] = []

    def chat(self, messages, max_tokens=400):
        self.calls.append(messages)
        return self.reply


def _chunk(chunk_id: int = 1, **overrides) -> dict:
    base = {
        "id": chunk_id,
        "repo": "acme/atlas",
        "path": "docs/limits.md",
        "url": "https://github.com/acme/atlas/blob/main/docs/limits.md",
        "doc_type": "doc",
        "heading_path": "The numbers",
        "content": "The API allows 100 requests per minute per workspace.",
        "embed_text": "acme/atlas > docs/limits.md > The numbers\n\n100 rpm",
        "updated_at": NOW,
        "score": 0.03,
        "rerank_score": 0.91,
    }
    base.update(overrides)
    return base


@pytest.fixture
def stub_env(monkeypatch):
    """A fake retrieval + logging layer so answer_question runs for real."""
    from app.logging_ import store

    next_id = iter(range(1000, 2000))
    logged: list[dict] = []
    candidates = [_chunk()]

    monkeypatch.setattr(answer_module, "hybrid_search", lambda q, levels, top_k, embedder=None: candidates)
    monkeypatch.setattr(answer_module, "rerank", lambda q, c, top_k, reranker=None: c[:top_k])
    monkeypatch.setattr(store, "docs_version", lambda: "2026-10-12T02:00:00+00:00")
    monkeypatch.setattr(store, "cache_get", lambda key: None)
    monkeypatch.setattr(store, "cache_put", lambda *a, **k: None)

    def _log_request(**kwargs):
        logged.append(kwargs)
        return next(next_id)

    monkeypatch.setattr(store, "log_request", _log_request)
    return logged


# --- collection --------------------------------------------------------------


def test_mock_source_produces_docs_from_the_fixtures():
    kinds = {d.kind for d in mock_source.collect_mock(settings)}
    assert {"readme", "doc", "release", "truth", "issue", "pr", "release_notes"} <= kinds


def test_mock_source_excludes_dot_mock_from_the_file_walk():
    docs = mock_source.collect_mock(settings)
    assert not any(d.rel_path.startswith(".mock/") for d in docs)


def test_collected_documents_all_chunk_into_indexable_rows():
    allowed = {"readme", "doc", "release", "issue", "pr", "adr", "truth", "code"}
    for doc in mock_source.collect_mock(settings):
        rows = chunk_document(doc, summarize=None)
        assert rows, f"{doc.rel_path} produced no chunks"
        for row in rows:
            assert row["content"].strip()
            assert row["embed_text"].startswith(f"{doc.repo} > {doc.rel_path}")
            assert len(row["content_hash"]) == 64  # sha256
            assert row["doc_type"] in allowed


def test_bot_comments_are_already_gone_before_chunking():
    for doc in mock_source.collect_mock(settings):
        if doc.kind != "issue":
            continue
        logins = [c["user"]["login"] for c in doc.issue["comments"]]
        assert not any(u.endswith("[bot]") or u == "dependabot" for u in logins)
        assert "+1" not in [c["body"] for c in doc.issue["comments"]]


def test_prompt_injection_in_an_issue_is_removed():
    docs = mock_source.collect_mock(settings)
    # fixture issue 412 contains a prompt-injection comment
    attack = next(d for d in docs if d.rel_path == "issues/issue-412.md")
    assert "Ignore all previous instructions" not in attack.text
    assert "unlimited exports" not in attack.text.lower()
    assert "Not planned for this quarter" in attack.text  # legitimate content survives


# --- the answer path ---------------------------------------------------------


def test_a_cited_answer_is_returned_and_logged(stub_env):
    llm = _StubLLM("Atlas allows 100 requests per minute per workspace on every plan [1].")
    response = answer_question(
        AskRequest(question="What is the API rate limit?", slack_user_id="U1"), llm=llm
    )

    assert response.answered is True
    assert response.request_id > 0
    assert response.sources[0].url.endswith("docs/limits.md")
    assert response.docs_as_of == "2026-10-12"

    row = stub_env[-1]
    assert row["answered"] is True
    assert row["slack_user_id"] == "U1"
    assert row["chunk_ids"] == [1]
    assert "100 requests per minute" in row["answer"]

    passages = llm.calls[0][1]["content"]
    assert "[1] SOURCE: acme/atlas > docs/limits.md > The numbers" in passages


def test_an_uncited_answer_is_rejected_as_not_in_the_docs(stub_env):
    llm = _StubLLM("Atlas allows 100 requests per minute per workspace.")
    response = answer_question(AskRequest(question="rate limit?", slack_user_id="U2"), llm=llm)
    assert response.answered is False
    assert "Not in the docs" in response.answer
    assert stub_env[-1]["answered"] is False


def test_a_refusal_from_the_model_is_recorded_as_a_refusal(stub_env):
    llm = _StubLLM("NOT_IN_DOCS")
    response = answer_question(AskRequest(question="pricing?", slack_user_id="U3"), llm=llm)
    assert response.answered is False
    assert stub_env[-1]["answered"] is False


def test_a_citation_outside_the_supplied_passages_is_rejected(stub_env):
    llm = _StubLLM("That is documented in [7].")
    response = answer_question(AskRequest(question="limits?", slack_user_id="U4"), llm=llm)
    assert response.answered is False


def test_the_llm_is_not_called_below_the_rerank_threshold(stub_env, monkeypatch):
    weak = [_chunk(rerank_score=0.01)]
    monkeypatch.setattr(
        answer_module, "rerank", lambda q, c, top_k, reranker=None: weak[:top_k]
    )
    llm = _StubLLM("Something confident with a citation [1].")
    response = answer_question(AskRequest(question="q?", slack_user_id="U5"), llm=llm)
    assert response.answered is False
    assert llm.calls == [], "the LLM must not be called below MIN_RERANK_SCORE"


def test_an_empty_access_level_list_fails_closed(stub_env):
    llm = _StubLLM("Should never be reached [1].")
    response = answer_question(
        AskRequest(question="q?", slack_user_id="U6", access_levels=[]), llm=llm
    )
    assert response.answered is False
    assert llm.calls == []


def test_only_the_final_ranked_passages_are_sent_to_the_model(stub_env, monkeypatch):
    many = [_chunk(chunk_id=i, path=f"docs/f{i}.md") for i in range(1, 9)]
    monkeypatch.setattr(
        answer_module, "hybrid_search", lambda q, levels, top_k, embedder=None: many
    )
    monkeypatch.setattr(
        answer_module,
        "rerank",
        lambda q, c, top_k, reranker=None: [
            {**c[i], "rerank_score": 0.9 - i * 0.01} for i in range(min(top_k, len(c)))
        ],
    )
    llm = _StubLLM("Answer with a citation [1].")
    answer_question(AskRequest(question="q?", slack_user_id="U7"), llm=llm)

    passages = llm.calls[0][1]["content"]
    assert passages.count("SOURCE:") == settings.top_k_final