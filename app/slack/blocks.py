"""Block Kit builders for Slack replies (spec section 13)."""

from __future__ import annotations

from app.models import AskResponse

HELPFUL = "prodex_feedback_helpful"
NOT_HELPFUL = "prodex_feedback_bad"
ESCALATE = "prodex_escalate"


def _feedback_buttons(request_id: int) -> list[dict]:
    return [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "👍 Helpful"},
            "style": "primary",
            "action_id": HELPFUL,
            "value": str(request_id),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "👎 Not helpful"},
            "action_id": NOT_HELPFUL,
            "value": str(request_id),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Escalate to engineering"},
            "style": "danger",
            "action_id": ESCALATE,
            "value": str(request_id),
        },
    ]


def _docs_as_of_context(response: AskResponse) -> dict:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_Docs as of {response.docs_as_of}_"}],
    }


def answer_blocks(response: AskResponse) -> list[dict]:
    """Answer + a compact source context + feedback buttons."""
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": response.answer}},
    ]

    if response.sources:
        lines = [
            f"• <{s.url}|{s.title}>" + (f" _(updated {s.updated_at})_" if s.updated_at else "")
            for s in response.sources
        ]
        context = "\n".join(lines)
        if response.docs_as_of:
            context += f"\n_Docs as of {response.docs_as_of}_"
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": context}]})
    elif response.docs_as_of:
        blocks.append(_docs_as_of_context(response))

    blocks.append({"type": "actions", "elements": _feedback_buttons(response.request_id)})
    return blocks


def not_in_docs_blocks(response: AskResponse) -> list[dict]:
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": response.answer}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Escalate to engineering"},
                    "style": "danger",
                    "action_id": ESCALATE,
                    "value": str(response.request_id),
                }
            ],
        },
    ]
    if response.docs_as_of:
        blocks.append(_docs_as_of_context(response))
    return blocks


def blocks_for(response: AskResponse) -> list[dict]:
    return answer_blocks(response) if response.answered else not_in_docs_blocks(response)


def confirmation(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def escalation_message(question: str, request_id: int, asked_by: str | None) -> str:
    who = f"<@{asked_by}>" if asked_by else "unknown"
    return (
        f":rotating_light: *Escalated from ProdEx* (request `{request_id}`)\n"
        f"*Question:* {question}\n"
        f"*Asked by:* {who}"
    )