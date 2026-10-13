"""Slack bot: Bolt for Python in Socket Mode (spec section 13).

Thin layer. It acknowledges within three seconds, posts a "Looking this up…"
placeholder, then calls the API in a worker thread and updates the same message.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict

import httpx
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.config import settings
from app.models import AskResponse
from app.slack import blocks as b

log = logging.getLogger(__name__)

DEDUPE_TTL_SECONDS = 300
DEDUPE_MAX = 500
HEADER = {"X-Internal-Key": settings.internal_api_key}


# --- event de-duplication (spec section 13) ---------------------------------

_seen: OrderedDict[str, float] = OrderedDict()
_seen_lock = threading.Lock()


def is_duplicate(event_id: str | None) -> bool:
    """Slack retries deliveries; answering twice would post two answers."""
    if not event_id:
        return False
    now = time.time()
    with _seen_lock:
        for key, stamp in list(_seen.items()):
            if now - stamp > DEDUPE_TTL_SECONDS:
                _seen.pop(key, None)
        if event_id in _seen:
            return True
        _seen[event_id] = now
        while len(_seen) > DEDUPE_MAX:
            _seen.popitem(last=False)
    return False


# --- API client --------------------------------------------------------------


def call_api(path: str, payload: dict, timeout: float = 120.0) -> dict:
    url = f"{settings.api_base_url.rstrip('/')}{path}"
    response = httpx.post(url, json=payload, headers=HEADER, timeout=timeout)
    response.raise_for_status()
    return response.json()


def ask(question: str, slack_user_id: str, channel_type: str) -> AskResponse:
    data = call_api("/ask", {"question": question, "slack_user_id": slack_user_id,
                             "channel_type": channel_type})
    return AskResponse(**data)


# --- Slack plumbing ----------------------------------------------------------


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _placeholder(client, channel: str, thread_ts: str | None) -> str | None:
    """Post 'Looking this up…' and return the message timestamp to update later."""
    posted = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Looking this up…",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "_Looking this up…_"}}],
    )
    return posted.get("ts")


def _answer_in_background(client, channel: str, placeholder_ts: str | None, question: str,
                          user_id: str, channel_type: str) -> None:
    try:
        response = ask(question, user_id, channel_type)
        client.chat_update(
            channel=channel,
            ts=placeholder_ts,
            text=response.answer[:200],
            blocks=b.blocks_for(response),
        )
    except Exception as exc:
        log.exception("answer failed")
        client.chat_update(
            channel=channel,
            ts=placeholder_ts,
            text="Sorry, something went wrong.",
            blocks=b.confirmation(
                f":warning: I could not answer that ({type(exc).__name__}). "
                "Please try again or escalate to engineering."
            ),
        )


def build_app() -> App:
    if not (settings.slack_bot_token and settings.slack_app_token):
        raise RuntimeError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")

    # Socket Mode: Slack connects over an authenticated WebSocket with the app-level
    # token, so there is no signed HTTP request for Bolt to verify (see DECISIONS.md D11).
    app = App(token=settings.slack_bot_token, request_verification_enabled=False)

    def allowed(channel_id: str) -> bool:
        return not settings.slack_allowed_channels or channel_id in settings.slack_allowed_channels

    def handle(event: dict, say, client, body: dict) -> None:
        event_id = (event.get("event") or {}).get("event_id") or body.get("event_id")
        if is_duplicate(event_id):
            log.info("ignoring duplicate event %s", event_id)
            return

        channel = event["channel"]
        if not allowed(channel):
            log.info("ignoring question from disallowed channel %s", channel)
            return

        channel_type = channel_type_of(event)
        question = _clean(event.get("text", ""))
        if channel_type == "channel":
            question = _strip_mention(question)

        if not question:
            say(text="Ask me something about the product, for example "
                     "`@prodex what is the API rate limit?`")
            return

        # in a channel, answer in a thread so the channel stays readable
        thread_ts = event.get("ts") if channel_type == "channel" else None
        placeholder_ts = _placeholder(client, channel, thread_ts)
        threading.Thread(
            target=_answer_in_background,
            args=(client, channel, placeholder_ts, question, event.get("user", ""), channel_type),
            daemon=True,
        ).start()

    @app.event("app_mention")
    def on_mention(event, say, client, logger):
        handle(event, say, client, event)

    @app.event("message")
    def on_dm(event, say, client, logger):
        # Bolt routes direct messages here; ignore channel chatter and bot echoes
        if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
            return
        handle(event, say, client, event)

    @app.command("/askproduct")
    def on_command(ack, body, say, client, respond, command):
        ack()
        question = _clean((command.get("text") or "").strip('"'))
        channel = body["channel_id"]
        if not allowed(channel):
            respond("ProdEx is not available in this channel.")
            return
        if not question:
            respond("Usage: `/askproduct <your question>`")
            return
        placeholder_ts = _placeholder(client, channel, None)
        threading.Thread(
            target=_answer_in_background,
            args=(client, channel, placeholder_ts, question, body.get("user_id", ""),
                  channel_type_of({"channel": channel})),
            daemon=True,
        ).start()

    # --- buttons ---

    @app.action(b.HELPFUL)
    @app.action(b.NOT_HELPFUL)
    def on_feedback(ack, body, client):
        ack()
        action = body["actions"][0]
        value = 1 if action["action_id"] == b.HELPFUL else -1
        request_id = int(action["value"])
        try:
            call_api("/feedback", {"request_id": request_id, "value": value})
        except Exception:
            log.exception("feedback call failed")
            return
        label = "👍 Thanks - noted as helpful." if value == 1 else "👎 Thanks - we'll look at it."
        _update_message(client, body, label)

    @app.action(b.ESCALATE)
    def on_escalate(ack, body, client):
        ack()
        request_id = int(body["actions"][0]["value"])
        try:
            call_api("/escalate", {"request_id": request_id,
                                   "slack_user_id": body.get("user", {}).get("id")})
        except Exception:
            log.exception("escalate call failed")
            _update_message(
                client, body, ":warning: Escalation failed. Please contact engineering directly."
            )
            return
        _update_message(
            client, body, ":rotating_light: Sent to engineering. They'll follow up in this thread."
        )

    return app


def _update_message(client, body: dict, text: str) -> None:
    message = body.get("message", {})
    channel = body.get("channel", {}).get("id")
    ts = message.get("ts")
    if channel and ts:
        client.chat_update(channel=channel, ts=ts, text=text, blocks=b.confirmation(text))


def channel_type_of(event: dict) -> str:
    return "channel" if event.get("channel_type") in ("channel", "group") else "dm"


def _strip_mention(text: str) -> str:
    parts = text.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 and text.startswith("<@") else text


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log.info("starting Slack bot (allowed channels: %s)", settings.slack_allowed_channels or "all")
    SocketModeHandler(build_app(), os.environ.get("SLACK_APP_TOKEN", settings.slack_app_token)).start()


if __name__ == "__main__":
    main()