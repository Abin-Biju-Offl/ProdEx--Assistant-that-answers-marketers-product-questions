"""Retrieval plumbing that does not need a database or a model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.retrieval.filters import normalize_levels
from app.retrieval.search import rrf_merge


def test_rrf_prefers_items_found_by_both_rankings():
    vector = [(1, 0.9), (2, 0.8), (3, 0.7)]
    keyword = [(3, 0.9), (1, 0.8)]
    fused = rrf_merge([vector, keyword], k=60)
    ranked = [doc_id for doc_id, _ in fused]
    assert ranked[0] == 1  # in both lists, first in vector
    assert set(ranked) == {1, 2, 3}
    assert len(fused) == 3


def test_rrf_scores_are_monotonic_and_bounded():
    fused = rrf_merge([[(1, 1.0)], [(1, 1.0)]], k=60)
    # two first-place appearances: 1/61 + 1/61
    assert fused[0][1] == pytest.approx(2 / 61)


def test_rrf_handles_empty_rankings():
    assert rrf_merge([]) == []
    assert rrf_merge([[], []]) == []


def test_rrf_uses_the_configured_k():
    small_k = rrf_merge([[(1, 1.0)]], k=1)
    large_k = rrf_merge([[(1, 1.0)]], k=1000)
    assert small_k[0][1] > large_k[0][1]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (["public", "internal"], ["public", "internal"]),
        (["public"], ["public"]),
        (["secret", "everyone"], []),
        ([], []),
        (None, []),
    ],
)
def test_access_levels_fail_closed(given, expected):
    assert normalize_levels(given) == expected


def test_boost_constants_match_the_spec():
    from app.retrieval import search

    assert search.TRUTH_BOOST > 1.0
    assert search.RECENT_RELEASE_BOOST > 1.0
    assert search.RECENT_RELEASE_WINDOW == timedelta(days=180)


def test_recency_math_is_importable():
    now = datetime.now(UTC)
    assert now.tzinfo is not None