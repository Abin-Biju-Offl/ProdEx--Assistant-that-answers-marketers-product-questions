"""API contract tests. Skipped automatically when no database is reachable."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings

KEY = {"X-Internal-Key": settings.internal_api_key}


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _require_db(client):
    if client.get("/health").json().get("database") != "ok":
        pytest.skip("no database reachable")


def test_health_is_open_and_reports_the_corpus(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "chunks" in body and "docs_version" in body


@pytest.mark.parametrize("path", ["/ask", "/feedback", "/escalate", "/ingest"])
def test_endpoints_require_the_internal_key(client, path):
    assert client.post(path, json={}).status_code == 401
    assert client.post(path, json={}, headers={"X-Internal-Key": "wrong"}).status_code == 401


def test_ask_returns_the_documented_shape(client):
    r = client.post(
        "/ask",
        json={"question": "What is the API rate limit?", "slack_user_id": "U123", "channel_type": "dm"},
        headers=KEY,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for field in ("request_id", "answered", "answer", "sources", "confidence", "docs_as_of"):
        assert field in body
    assert isinstance(body["answered"], bool)


def test_feedback_records_a_vote(client):
    r = client.post("/ask", json={"question": "Do you support SSO?", "slack_user_id": "U9"}, headers=KEY)
    request_id = r.json()["request_id"]
    feedback = client.post("/feedback", json={"request_id": request_id, "value": 1}, headers=KEY)
    assert feedback.status_code == 200
    assert client.post("/feedback", json={"request_id": 99999999, "value": 1}, headers=KEY).status_code == 404


def test_feedback_rejects_out_of_range_values(client):
    assert client.post("/feedback", json={"request_id": 1, "value": 5}, headers=KEY).status_code == 422


def test_ask_is_logged_with_the_slack_id_only(client):
    client.post("/ask", json={"question": "Logged question", "slack_user_id": "U-LOG"}, headers=KEY)
    row = db_row_for("Logged question")
    assert row is not None
    assert row["slack_user_id"] == "U-LOG"
    assert "@" not in row["slack_user_id"] and "slack.com" not in row["slack_user_id"]


def db_row_for(question: str):
    from app import db

    return db.query_one("SELECT * FROM requests WHERE question = %s ORDER BY id DESC LIMIT 1", (question,))


def test_ingest_starts_in_the_background(client):
    r = client.post("/ingest", headers=KEY)
    assert r.status_code == 200
    assert r.json()["status"] == "started"