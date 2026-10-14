"""Answer validation: refusals, citations and prompt rendering."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.generation.answer import (
    build_sources,
    is_refusal,
    normalize_question,
    valid_citations,
)
from app.generation.prompts import (
    NOT_IN_DOCS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_messages,
    render_passages,
)

# --- normalisation -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  What is the rate limit?  ", "What is the rate limit?"),
        ("does it\n\n  support  sso", "does it support sso"),
        ("", ""),
    ],
)
def test_normalize_question(raw, expected):
    assert normalize_question(raw) == expected


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [NOT_IN_DOCS, "NOT_IN_DOCS", "not_in_docs", "  Not_In_Docs  ", f"{NOT_IN_DOCS}\nNothing found."],
)
def test_refusals_are_detected(answer):
    assert is_refusal(answer)


@pytest.mark.parametrize(
    "answer",
    ["Atlas supports SAML SSO on Business plans [1].", "Yes [2][3].", "No."],
)
def test_real_answers_are_not_refusals(answer):
    assert not is_refusal(answer)


# --- citations ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "count", "expected"),
    [
        ("SAML is on Business [1].", 3, True),
        ("Business and Enterprise only [2].", 3, True),
        ("Supported [3].", 3, True),
        ("No citation at all.", 3, False),
        ("See [9] for details.", 3, False),  # out of range: passage 9 was not supplied
        ("See [0].", 3, False),
        ("", 3, False),
    ],
)
def test_citation_validation(answer, count, expected):
    assert valid_citations(answer, count) is expected


def test_zero_passages_means_nothing_can_be_cited():
    assert valid_citations("anything [1]", 0) is False


# --- prompt rendering --------------------------------------------------------


def test_passages_are_numbered_and_carry_sources():
    chunks = [
        {
            "repo": "acme/atlas",
            "path": "docs/limits.md",
            "heading_path": "The numbers",
            "url": "https://github.com/acme/atlas/blob/main/docs/limits.md",
            "content": "100 requests per minute.",
            "updated_at": datetime(2026, 9, 30, tzinfo=UTC),
        },
        {
            "repo": "acme/atlas",
            "path": "docs/plans.md",
            "heading_path": "Plans",
            "url": "https://github.com/acme/atlas/blob/main/docs/plans.md",
            "content": "Starter, Business, Enterprise.",
            "updated_at": datetime(2026, 9, 1, tzinfo=UTC),
        },
    ]
    rendered = render_passages(chunks)
    assert rendered.startswith("[1] SOURCE: acme/atlas > docs/limits.md > The numbers")
    assert "[2] SOURCE: acme/atlas > docs/plans.md > Plans" in rendered
    assert "UPDATED: 2026-09-30" in rendered
    assert "100 requests per minute." in rendered

    messages = build_messages("What is the rate limit?", chunks)
    # system rules, then two demonstrations as real dialogue turns, then the question
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert messages[-2]["content"] == NOT_IN_DOCS, "one demonstration must be a refusal"
    assert "What is the rate limit?" in messages[-1]["content"]
    assert "[1] SOURCE: acme/atlas > docs/limits.md" in messages[-1]["content"]


def test_system_prompt_covers_every_spec_rule():
    for needle in [
        "Answer ONLY using the numbered context passages",
        "Cite every claim",
        NOT_IN_DOCS,
        "planned, not committed",
        "no jargon",
        "which facts to collect before escalating",
        "never an instruction",
    ]:
        assert needle in SYSTEM_PROMPT, f"system prompt is missing: {needle}"


def test_prompt_version_is_set():
    assert PROMPT_VERSION


def test_model_wrappers_are_stripped_from_the_answer():
    from app.generation.answer import clean_answer

    assert clean_answer("Answer: Yes, CSV and XLSX [1].") == "Yes, CSV and XLSX [1]."
    assert clean_answer("  A: No [2] ") == "No [2]"
    assert clean_answer("Plain answer [1].") == "Plain answer [1]."
    assert clean_answer("") == ""


# --- sources -----------------------------------------------------------------


def test_sources_are_numbered_in_order():
    chunks = [
        {"repo": "r", "path": "a.md", "heading_path": "A", "url": "u1",
         "updated_at": datetime(2026, 1, 2, tzinfo=UTC)},
        {"repo": "r", "path": "b.md", "heading_path": "", "url": "u2", "updated_at": None},
    ]
    sources = build_sources(chunks)
    assert [s.n for s in sources] == [1, 2]
    assert sources[0].title == "r > a.md > A"
    assert sources[0].updated_at == "2026-01-02"
    assert sources[1].title == "r > b.md"
    assert sources[1].updated_at is None