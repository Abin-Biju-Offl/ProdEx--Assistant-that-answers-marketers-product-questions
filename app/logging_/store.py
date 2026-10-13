"""Request log, feedback, answer cache and retention (spec section 8/9).

Slack user IDs only: never names, never emails (spec section 14.5).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app import db

log = logging.getLogger(__name__)

DOCS_VERSION_KEY = "docs_version"


# --- meta -------------------------------------------------------------------


def get_meta(key: str) -> str | None:
    row = db.query_one("SELECT value FROM meta WHERE key = %s", (key,))
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    db.execute(
        "INSERT INTO meta (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, value),
    )


def docs_version() -> str:
    """Timestamp of the last successful ingest. Part of the answer-cache key."""
    return get_meta(DOCS_VERSION_KEY) or "empty"


# --- request log ------------------------------------------------------------


def log_request(
    *,
    slack_user_id: str,
    question: str,
    answer: str | None,
    answered: bool,
    top_score: float | None,
    chunk_ids: list[int],
    latency_ms: int,
    model: str | None,
    channel_type: str | None = None,
    cached: bool = False,
) -> int:
    row = db.query_one(
        """
        INSERT INTO requests (slack_user_id, channel_type, question, answer, answered,
                              top_score, chunk_ids, latency_ms, model, cached)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            slack_user_id,
            channel_type,
            question,
            answer,
            answered,
            top_score,
            chunk_ids,
            latency_ms,
            model,
            cached,
        ),
    )
    return int(row["id"])


def set_feedback(request_id: int, value: int, note: str | None = None) -> bool:
    rows = db.execute(
        "UPDATE requests SET feedback = %s, feedback_note = %s WHERE id = %s",
        (value, note, request_id),
    )
    return rows > 0


def mark_escalated(request_id: int) -> bool:
    return db.execute("UPDATE requests SET escalated = true WHERE id = %s", (request_id,)) > 0


def get_request(request_id: int) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM requests WHERE id = %s", (request_id,))


def purge_old_requests(days: int) -> int:
    """Retention job (spec section 9). Deletes request logs, not the knowledge base."""
    if days <= 0:
        return 0
    return db.execute(
        "DELETE FROM requests WHERE created_at < now() - make_interval(days => %s)",
        (days,),
    )


# --- answer cache -----------------------------------------------------------


def cache_key(normalized_question: str, version: str) -> str:
    return hashlib.sha256(f"{normalized_question}|{version}".encode()).hexdigest()


def cache_get(key: str) -> dict | None:
    row = db.query_one("SELECT payload FROM answer_cache WHERE cache_key = %s", (key,))
    return json.loads(row["payload"]) if row else None


def cache_put(key: str, question: str, version: str, payload: dict) -> None:
    db.execute(
        "INSERT INTO answer_cache (cache_key, question, docs_version, payload) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (cache_key) DO NOTHING",
        (key, question, version, json.dumps(payload)),
    )


def purge_stale_cache(version: str) -> int:
    return db.execute("DELETE FROM answer_cache WHERE docs_version <> %s", (version,))


# --- ingest runs ------------------------------------------------------------


def start_ingest_run(repo: str | None) -> int:
    row = db.query_one(
        "INSERT INTO ingest_runs (repo) VALUES (%s) RETURNING id", (repo,)
    )
    return int(row["id"])


def finish_ingest_run(run_id: int, *, status: str, error: str | None = None, **counts: int) -> None:
    db.execute(
        """
        UPDATE ingest_runs
        SET finished_at = now(), status = %s, error = %s,
            files_seen = %s, files_indexed = %s, files_skipped_secrets = %s,
            chunks_written = %s, chunks_deprecated = %s
        WHERE id = %s
        """,
        (
            status,
            (error or "")[:500] or None,
            counts.get("files_seen", 0),
            counts.get("files_indexed", 0),
            counts.get("files_skipped_secrets", 0),
            counts.get("chunks_written", 0),
            counts.get("chunks_deprecated", 0),
            run_id,
        ),
    )


def touch_docs_version() -> str:
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    set_meta(DOCS_VERSION_KEY, stamp)
    return stamp


def corpus_stats() -> dict[str, int]:
    row = db.query_one(
        "SELECT count(*) FILTER (WHERE status = 'current') AS current, "
        "count(*) AS total FROM chunks"
    )
    return {"current": int(row["current"]), "total": int(row["total"])}