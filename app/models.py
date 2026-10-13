"""Request/response schemas for the public API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    slack_user_id: str = Field(min_length=1, max_length=64)
    channel_type: str = Field(default="dm", pattern="^(dm|channel)$")
    # Phase 1: every authenticated user sees public + internal. The field exists so
    # the access-level filter in app/retrieval/filters.py has something to read.
    access_levels: list[str] = Field(default_factory=lambda: ["public", "internal"])


class Source(BaseModel):
    n: int
    title: str
    url: str
    updated_at: str | None = None


class AskResponse(BaseModel):
    request_id: int
    answered: bool
    answer: str
    sources: list[Source] = Field(default_factory=list)
    confidence: float | None = None
    docs_as_of: str | None = None
    owner_hint: str | None = None
    cached: bool = False


class FeedbackRequest(BaseModel):
    request_id: int
    value: int = Field(ge=-1, le=1)
    note: str | None = None


class EscalateRequest(BaseModel):
    request_id: int
    question: str | None = None
    slack_user_id: str | None = None


class IngestResponse(BaseModel):
    run_id: int
    repo: str | None
    files_seen: int
    files_indexed: int
    files_skipped_secrets: int
    chunks_written: int
    chunks_deprecated: int


class HealthResponse(BaseModel):
    status: str
    database: str
    docs_version: str | None = None
    chunks: int = 0