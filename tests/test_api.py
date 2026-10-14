"""API contract tests. Skipped automatically when no database is reachable.

Uses httpx's ASGITransport rather than starlette's TestClient: the locked httpx
version is newer than TestClient supports.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(scope="module")
async def client():
    from app.main import app, lifespan

    transport = httpx.ASGITransport(app=app)
    async with lifespan(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture(autouse=True)
async def _require_db(client):
    response = await client.get("/health")
    if response.json().get("database") != "ok":
        pytest.skip("no database reachable")


def _headers() -> dict:
    from app.config import settings

    return {"X-Internal-Key": settings.internal_api_key}


async def test_health_is_open_and_reports_the_corpus(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "chunks" in body and "docs_version" in body


@pytest.mark.parametrize("path", ["/ask", "/feedback", "/escalate", "/ingest"])
async def test_endpoints_require_the_internal_key(client, path):
    assert (await client.post(path, json={})).status_code == 401
    bad = await client.post(path, json={}, headers={"X-Internal-Key": "wrong"})
    assert bad.status_code == 401


async def test_ask_returns_the_documented_shape(client):
    response = await client.post(
        "/ask",
        json={"question": "What is the API rate limit?", "slack_user_id": "U123", "channel_type": "dm"},
        headers=_headers(),
        timeout=300,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    for field in ("request_id", "answered", "answer", "sources", "confidence", "docs_as_of"):
        assert field in body
    assert isinstance(body["answered"], bool)
    assert isinstance(body["sources"], list)


async def test_ask_refuses_rather_than_guessing(client):
    response = await client.post(
        "/ask",
        json={"question": "What is the Enterprise price in euros?", "slack_user_id": "U-REFUSE"},
        headers=_headers(),
        timeout=300,
    )
    body = response.json()
    assert body["answered"] is False
    assert "Not in the docs" in body["answer"]
    assert body["owner_hint"]


async def test_ask_rejects_an_unknown_channel_type(client):
    response = await client.post(
        "/ask", json={"question": "hi", "slack_user_id": "U1", "channel_type": "carrier-pigeon"},
        headers=_headers(),
    )
    assert response.status_code == 422


async def test_feedback_records_a_vote(client):
    asked = await client.post(
        "/ask", json={"question": "Do you support SSO?", "slack_user_id": "U9"}, headers=_headers(),
        timeout=300,
    )
    request_id = asked.json()["request_id"]

    good = await client.post(
        "/feedback", json={"request_id": request_id, "value": 1}, headers=_headers()
    )
    assert good.status_code == 200

    missing = await client.post(
        "/feedback", json={"request_id": 99999999, "value": 1}, headers=_headers()
    )
    assert missing.status_code == 404


async def test_feedback_rejects_out_of_range_values(client):
    response = await client.post(
        "/feedback", json={"request_id": 1, "value": 5}, headers=_headers()
    )
    assert response.status_code == 422


async def test_escalate_records_the_flag(client):
    asked = await client.post(
        "/ask", json={"question": "Escalation test question", "slack_user_id": "U-ESC"},
        headers=_headers(), timeout=300,
    )
    request_id = asked.json()["request_id"]
    response = await client.post(
        "/escalate", json={"request_id": request_id, "slack_user_id": "U-ESC"}, headers=_headers()
    )
    assert response.status_code == 200

    from app.logging_ import store

    assert store.get_request(request_id)["escalated"] is True


async def test_escalate_unknown_request_is_404(client):
    response = await client.post("/escalate", json={"request_id": 99999999}, headers=_headers())
    assert response.status_code == 404


async def test_ask_is_logged_with_the_slack_id_only(client):
    from app import db

    await client.post(
        "/ask", json={"question": "Logged question", "slack_user_id": "U-LOG"}, headers=_headers(),
        timeout=300,
    )
    row = db.query_one(
        "SELECT * FROM requests WHERE question = %s ORDER BY id DESC LIMIT 1", ("Logged question",)
    )
    assert row is not None
    assert row["slack_user_id"] == "U-LOG"
    # never a name, an email or a display string
    assert "@" not in row["slack_user_id"]
    assert "slack.com" not in row["slack_user_id"]


async def test_ingest_starts_in_the_background(client):
    response = await client.post("/ingest", headers=_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "started"