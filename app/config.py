"""Environment-driven settings. Every tunable in the spec lives here."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: `NoDecode` stops pydantic-settings from JSON-parsing these before our own
#: validator runs, so `A=one,two` works in .env as well as `A=["one","two"]`.
CsvList = Annotated[list[str], NoDecode]


#: Hosts that mean "this machine". Anything else is a third party.
LOCAL_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "ollama",
    "host.docker.internal",
    "vllm",
    "",
}


def is_local_endpoint(url: str) -> bool:
    """True when a base URL points at this machine or the compose network."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return False
    return host in LOCAL_HOSTS


def _csv(value: object) -> object:
    """Accept a list from the environment in either `a,b,c` or `["a","b"]` form."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass  # fall through to the comma form
    return [item.strip().strip("\"'") for item in text.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Source of documents ------------------------------------------------
    github_source: Literal["mock", "github"] = "mock"
    github_repos: CsvList = []
    github_branch: str = "main"
    index_code: bool = False

    # --- GitHub App (read-only) --------------------------------------------
    github_app_id: str = ""
    github_app_installation_id: str = ""
    github_private_key_path: Path = Path("./secrets/github-app.pem")
    github_token: str = ""  # dev-only escape hatch; see docs/DECISIONS.md

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql://prodex:prodex@db:5432/prodex"
    metabase_db_url: str = "postgresql://metabase_ro:change_me@db:5432/prodex"

    # --- Models -------------------------------------------------------------
    # Any OpenAI-compatible /v1 endpoint works: Ollama, vLLM, LM Studio, Grok
    # (https://api.x.ai/v1), NVIDIA NIM (https://integrate.api.nvidia.com/v1), OpenAI.
    # Whether it is local is decided from the host, not from a flag.
    llm_base_url: str = "http://ollama:11434/v1"
    llm_model: str = "qwen2.5:3b-instruct"
    llm_api_key: str = "ollama"
    llm_temperature: float = 0.0
    llm_timeout_seconds: int = 300

    embed_provider: Literal["local", "openai_compatible"] = "local"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_dim: int = 384

    rerank_provider: Literal["local", "none"] = "local"
    rerank_model: str = "BAAI/bge-reranker-base"

    allow_external_providers: bool = False

    # --- Retrieval ----------------------------------------------------------
    top_k_retrieve: int = 20
    top_k_keyword: int = 20
    rrf_k: int = 60
    top_k_final: int = 5
    min_rerank_score: float = 0.30

    # --- Chunking -----------------------------------------------------------
    chunk_min_tokens: int = 100
    chunk_max_tokens: int = 600
    chunk_overlap_ratio: float = 0.12
    summarize_issue_threads: bool = True

    # --- Slack --------------------------------------------------------------
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_allowed_channels: CsvList = []
    escalation_channel: str = ""
    owner_hint: str = "the product owner"
    api_base_url: str = "http://api:8000"

    # --- API / ops ----------------------------------------------------------
    internal_api_key: str = "change-me-generate-a-long-random-value"
    log_retention_days: int = 180

    # --- Local (non-secret) paths ------------------------------------------
    fixtures_dir: Path = Path("./fixtures/repo")

    @field_validator("github_repos", "slack_allowed_channels", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        return _csv(value)

    # --- Helpers ------------------------------------------------------------

    def github_credentials_present(self) -> bool:
        return bool(self.github_app_id and self.github_app_installation_id)

    # --- external provider gate (spec section 14.8) -------------------------

    def require_local_only(self, what: str, endpoint: str) -> None:
        """Fail closed: product content never leaves the machine unless opted in.

        Decided from the URL rather than a separate provider flag, so repointing
        LLM_BASE_URL at a hosted service without flipping the switch refuses to
        start rather than silently shipping the index to a third party.
        """
        if is_local_endpoint(endpoint):
            return
        if not self.allow_external_providers:
            raise RuntimeError(
                f"{what} is pointed at {endpoint!r}, which is not this machine. That "
                "sends product documentation to a third party. Set "
                "ALLOW_EXTERNAL_PROVIDERS=true to allow it deliberately "
                "(spec section 14.8), or point it back at a local endpoint."
            )

    def external_providers_allowed(self, provider: str, endpoint: str | None = None) -> bool:
        """Back-compat wrapper used by the embedding and reranking providers."""
        if provider in ("local", "none"):
            return True
        self.require_local_only(f"provider {provider!r}", endpoint or "")
        return True

    def llm_is_local(self) -> bool:
        return is_local_endpoint(self.llm_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()