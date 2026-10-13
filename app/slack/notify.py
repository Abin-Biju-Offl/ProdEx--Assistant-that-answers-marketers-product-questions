"""Outbound Slack notifications (escalations). Used by the API, not the bot."""

from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger(__name__)


def notify_escalation(request_row: dict, asked_by: str | None = None) -> bool:
    """Post an escalation to ESCALATION_CHANNEL. Silently skipped when unset."""
    from app.slack.blocks import escalation_message

    channel = settings.escalation_channel
    if not channel:
        log.info("escalation recorded for request %s (no ESCALATION_CHANNEL configured)",
                 request_row.get("id"))
        return False
    if not settings.slack_bot_token:
        log.warning("escalation requested but SLACK_BOT_TOKEN is not set")
        return False

    from slack_sdk import WebClient

    client = WebClient(token=settings.slack_bot_token)
    text = escalation_message(request_row.get("question", ""), int(request_row["id"]), asked_by)
    client.chat_postMessage(channel=channel, text=text, unfurl_links=False)
    log.info("escalation posted for request %s", request_row.get("id"))
    return True