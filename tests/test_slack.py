"""Slack layer: Block Kit shape and event de-duplication."""

from __future__ import annotations

from app.models import AskResponse, Source
from app.slack import blocks as b
from app.slack.bot import DEDUPE_TTL_SECONDS, _strip_mention, is_duplicate


def _response(**kwargs) -> AskResponse:
    source = Source(
        n=1, title="acme/atlas > docs/plans.md > Plans", url="https://u", updated_at="2026-09-01"
    )
    base = {
        "request_id": 42,
        "answered": True,
        "answer": "SAML SSO is on Business and Enterprise [1].",
        "sources": [source],
        "confidence": 0.82,
        "docs_as_of": "2026-10-12",
    }
    base.update(kwargs)
    return AskResponse(**base)


def test_answer_message_has_text_sources_buttons_and_docs_date():
    rendered = b.blocks_for(_response())
    kinds = [block["type"] for block in rendered]
    assert kinds == ["section", "context", "actions"]

    text = rendered[0]["text"]["text"]
    assert "SAML" in text

    context = rendered[1]["elements"][0]["text"]
    assert "https://u" in context and "acme/atlas" in context
    assert "Docs as of 2026-10-12" in context

    action_ids = [e["action_id"] for e in rendered[2]["elements"]]
    assert action_ids == [b.HELPFUL, b.NOT_HELPFUL, b.ESCALATE]
    assert all(e["value"] == "42" for e in rendered[2]["elements"])


def test_not_in_docs_message_shows_owner_and_escalate_only():
    response = _response(
        answered=False,
        answer="Not in the docs. Ask the product owner.",
        sources=[],
        confidence=None,
        owner_hint="the product owner",
    )
    rendered = b.blocks_for(response)
    kinds = [block["type"] for block in rendered]
    assert kinds == ["section", "actions", "context"]
    action_ids = [e["action_id"] for e in rendered[1]["elements"]]
    assert action_ids == [b.ESCALATE]
    assert "the product owner" in rendered[0]["text"]["text"]


def test_escalation_message_mentions_the_request_id():
    text = b.escalation_message("Why is export failing?", 42, "U123")
    assert "42" in text and "Why is export failing?" in text and "<@U123>" in text


def test_escalation_message_handles_a_missing_user():
    text = b.escalation_message("Why is export failing?", 42, None)
    assert "unknown" in text


# --- de-duplication ----------------------------------------------------------


def test_duplicate_events_are_ignored_once():
    assert is_duplicate("Ev123") is False
    assert is_duplicate("Ev123") is True


def test_different_events_are_not_blocked():
    assert is_duplicate("EvA") is False
    assert is_duplicate("EvB") is False


def test_missing_event_id_never_deduplicates():
    assert is_duplicate(None) is False
    assert is_duplicate(None) is False


def test_dedupe_window_is_five_minutes():
    assert DEDUPE_TTL_SECONDS == 300


# --- text handling -----------------------------------------------------------


def test_mention_is_stripped_from_a_channel_question():
    assert _strip_mention("<@U123> what is the rate limit") == "what is the rate limit"
    assert _strip_mention("what is the rate limit") == "what is the rate limit"