"""Hybrid search: vector + Postgres full-text, merged with RRF, then boosted.

Spec section 10 steps 3-5.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from app import db
from app.retrieval.embed import Embedder, embed_text_vector, get_embedder
from app.retrieval.filters import BASE_PREDICATE
from app.retrieval.rerank import Reranker, get_reranker

# --- spec section 10 step 4 boosts ---
TRUTH_BOOST = 1.30
RECENT_RELEASE_BOOST = 1.10
RECENT_RELEASE_WINDOW = timedelta(days=180)
FRESHNESS_MAX_BOOST = 0.05  # up to +5% for content updated today
FRESHNESS_HALFLIFE = timedelta(days=365)


def vector_search(
    embedder: Embedder, question: str, levels: list[str], limit: int
) -> list[tuple[int, float]]:
    vector = embed_text_vector(embedder.embed_query(question))
    rows = db.query(
        f"""
        SELECT c.id, 1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        WHERE {BASE_PREDICATE} AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
        """,
        (vector, levels, vector, limit),
    )
    return [(r["id"], float(r["score"])) for r in rows]


def keyword_search(question: str, levels: list[str], limit: int) -> list[tuple[int, float]]:
    rows = db.query(
        f"""
        SELECT c.id, ts_rank(c.tsv, plainto_tsquery('english', %s)) AS score
        FROM chunks c
        WHERE {BASE_PREDICATE}
          AND c.tsv @@ plainto_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s
        """,
        (question, levels, question, limit),
    )
    return [(r["id"], float(r["score"])) for r in rows]


def rrf_merge(rankings: list[list[tuple[int, float]]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: sum of 1/(k + rank) across all result lists."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda pair: pair[1], reverse=True)


def apply_boosts(
    candidates: list[tuple[int, float]],
    levels: list[str],
    now: datetime | None = None,
) -> list[tuple[int, float]]:
    """Multiply the fused score by small doc-type and freshness factors."""
    if not candidates:
        return []
    now = now or datetime.now(UTC)
    ids = [cid for cid, _ in candidates]
    rows = db.query(
        f"SELECT id, doc_type, updated_at FROM chunks c "
        f"WHERE c.id = ANY(%s) AND {BASE_PREDICATE}",
        (ids, levels),
    )
    meta = {r["id"]: r for r in rows}

    boosted: list[tuple[int, float]] = []
    for doc_id, score in candidates:
        row = meta.get(doc_id)
        if row is None:
            continue  # filtered out by access level after all
        factor = 1.0
        if row["doc_type"] == "truth":
            factor *= TRUTH_BOOST
        updated_at = row["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        age = now - updated_at
        if row["doc_type"] == "release" and age <= RECENT_RELEASE_WINDOW:
            factor *= RECENT_RELEASE_BOOST
        factor *= 1 + FRESHNESS_MAX_BOOST * math.exp(-age / FRESHNESS_HALFLIFE)
        boosted.append((doc_id, score * factor))

    return sorted(boosted, key=lambda pair: pair[1], reverse=True)


def fetch_chunks(doc_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not doc_ids:
        return {}
    rows = db.query(
        "SELECT id, repo, path, url, doc_type, heading_path, content, embed_text, "
        "version, access_level, status, updated_at "
        "FROM chunks WHERE id = ANY(%s)",
        (doc_ids,),
    )
    return {r["id"]: r for r in rows}


def hybrid_search(
    question: str, levels: list[str], top_k: int, embedder: Embedder | None = None
) -> list[dict]:
    """Vector + keyword -> RRF -> boosts -> top_k. Returns hydrated chunk dicts."""
    embedder = embedder or get_embedder()
    vector_hits = vector_search(embedder, question, levels, top_k)
    keyword_hits = keyword_search(question, levels, top_k)
    fused = rrf_merge([vector_hits, keyword_hits])
    boosted = apply_boosts(fused, levels)[:top_k]
    return hydrate(boosted)


def hydrate(scored: list[tuple[int, float]]) -> list[dict]:
    chunks = fetch_chunks([cid for cid, _ in scored])
    out = []
    for doc_id, score in scored:
        row = chunks.get(doc_id)
        if row is None:
            continue
        row = dict(row)
        row["score"] = score
        out.append(row)
    return out


def rerank(question: str, chunks: list[dict], top_k: int, reranker: Reranker | None = None) -> list[dict]:
    reranker = reranker or get_reranker()
    if not chunks:
        return []
    ranked = reranker.rerank(question, [c["embed_text"] for c in chunks])
    out = []
    for index, score in ranked[:top_k]:
        row = dict(chunks[index])
        row["rerank_score"] = score
        out.append(row)
    return out