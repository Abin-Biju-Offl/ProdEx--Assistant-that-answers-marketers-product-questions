"""ProdEx API (spec section 5, 10)."""

from __future__ import annotations

import asyncio
import logging
import secrets as std_secrets
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, status

from app import db
from app.config import settings
from app.generation.answer import answer_question
from app.ingestion import pipeline
from app.logging_ import store
from app.models import (
    AskRequest,
    AskResponse,
    EscalateRequest,
    FeedbackRequest,
    HealthResponse,
)

log = logging.getLogger(__name__)

RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


async def _retention_loop() -> None:
    while True:
        try:
            removed = await asyncio.to_thread(store.purge_old_requests, settings.log_retention_days)
            if removed:
                log.info("retention: removed %d request rows older than %d days",
                         removed, settings.log_retention_days)
        except Exception:
            log.exception("retention job failed")
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    await asyncio.to_thread(db.apply_schema)
    task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="ProdEx", version="1.0.0", lifespan=lifespan)


async def require_api_key(x_internal_key: str = Header(default="")) -> None:
    """Spec section 14.6: only the Slack bot and admins may call anything but /health."""
    if not std_secrets.compare_digest(x_internal_key, settings.internal_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing X-Internal-Key")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        db.execute("SELECT 1")
        stats = store.corpus_stats()
        return HealthResponse(
            status="ok", database="ok", docs_version=store.docs_version(), chunks=stats["current"]
        )
    except Exception:
        log.exception("health check failed")
        return HealthResponse(status="degraded", database="error", chunks=0)


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
async def ask(request: AskRequest) -> AskResponse:
    return await asyncio.to_thread(answer_question, request)


@app.post("/feedback", dependencies=[Depends(require_api_key)])
async def feedback(request: FeedbackRequest) -> dict:
    ok = await asyncio.to_thread(store.set_feedback, request.request_id, request.value, request.note)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown request_id")
    return {"ok": True, "request_id": request.request_id}


@app.post("/escalate", dependencies=[Depends(require_api_key)])
async def escalate(request: EscalateRequest) -> dict:
    row = await asyncio.to_thread(store.get_request, request.request_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown request_id")
    await asyncio.to_thread(store.mark_escalated, request.request_id)

    from app.slack.notify import notify_escalation

    await asyncio.to_thread(notify_escalation, row, request.slack_user_id)
    return {"ok": True, "request_id": request.request_id, "escalated": True}


@app.post("/ingest", dependencies=[Depends(require_api_key)])
async def ingest(
    background_tasks: BackgroundTasks,
    repo: str | None = Query(default=None, description="limit to one repository"),
) -> dict:
    """Kick off an ingestion. Runs in the background; check the ingest_runs table."""
    background_tasks.add_task(_run_ingest, repo)
    return {"status": "started", "repo": repo}


async def _run_ingest(repo: str | None) -> None:
    try:
        await asyncio.to_thread(pipeline.ingest, repo)
    except Exception:
        log.exception("background ingest failed")