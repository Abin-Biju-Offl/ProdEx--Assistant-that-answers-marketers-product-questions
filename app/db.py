"""Thin Postgres access layer: one pool, explicit SQL, no ORM (spec section 6)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = ConnectionPool(
                    settings.database_url,
                    min_size=1,
                    max_size=8,
                    timeout=10,
                    kwargs={"row_factory": dict_row},
                    open=True,
                )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as conn:
        yield conn


def query(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def query_one(sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: Sequence[Any] | None = None) -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def apply_schema(schema_path: Path | None = None) -> None:
    """Re-apply db/schema.sql. Every statement is IF NOT EXISTS, so this is a no-op
    on an already-migrated database (see db/migrations/README.md)."""
    path = schema_path or Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    ddl = path.read_text(encoding="utf-8")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(ddl)
    log.info("schema applied from %s", path)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None