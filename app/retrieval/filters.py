"""Access-level and status filters (spec section 10 step 2).

Phase 1 gives every authenticated user `public` + `internal`, but the filter lives in
code so Phase 2 can narrow it to per-user roles without touching the queries.
"""

from __future__ import annotations

ALLOWED_LEVELS = ("public", "internal")


def normalize_levels(levels: list[str] | None) -> list[str]:
    """Fail closed: anything unrecognised is dropped, empty input means nothing."""
    if not levels:
        return []
    return [lvl for lvl in levels if lvl in ALLOWED_LEVELS]


#: Reused verbatim in every retrieval query so filters cannot drift apart.
BASE_PREDICATE = "c.status = 'current' AND c.access_level = ANY(%s)"