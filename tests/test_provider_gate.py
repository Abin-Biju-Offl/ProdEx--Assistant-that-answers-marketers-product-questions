"""The external-provider gate (spec section 14.8).

Product content must never leave the machine unless someone opts in explicitly.
These tests cover the switch that enforces that.
"""

from __future__ import annotations

import pytest

from app.config import Settings, is_local_endpoint

# --- host detection ----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8000/v1",
        "http://ollama:11434/v1",
        "http://host.docker.internal:11434/v1",
        "http://vllm:8000/v1",
        "",
    ],
)
def test_local_endpoints(url):
    assert is_local_endpoint(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://api.x.ai/v1",
        "https://api.openai.com/v1",
        "https://integrate.api.nvidia.com/v1",
        "https://evil.example.com/v1",
    ],
)
def test_remote_endpoints(url):
    assert is_local_endpoint(url) is False


# --- the gate ---------------------------------------------------------------


def _settings(**overrides) -> Settings:
    base = {"llm_base_url": "http://ollama:11434/v1", "allow_external_providers": False}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def test_local_llm_needs_no_opt_in():
    cfg = _settings()
    assert cfg.llm_is_local() is True
    cfg.require_local_only("LLM_BASE_URL", cfg.llm_base_url)  # must not raise


def test_remote_llm_is_refused_by_default():
    """The important one: repointing at a hosted provider must fail closed."""
    cfg = _settings(llm_base_url="https://api.x.ai/v1")
    assert cfg.llm_is_local() is False
    with pytest.raises(RuntimeError, match="ALLOW_EXTERNAL_PROVIDERS"):
        cfg.require_local_only("LLM_BASE_URL", cfg.llm_base_url)


def test_remote_llm_is_allowed_once_opted_in():
    cfg = _settings(llm_base_url="https://api.x.ai/v1", allow_external_providers=True)
    cfg.require_local_only("LLM_BASE_URL", cfg.llm_base_url)  # must not raise


def test_error_message_names_the_setting_and_the_host():
    cfg = _settings(llm_base_url="https://api.openai.com/v1")
    with pytest.raises(RuntimeError) as exc:
        cfg.require_local_only("LLM_BASE_URL", cfg.llm_base_url)
    message = str(exc.value)
    assert "api.openai.com" in message
    assert "ALLOW_EXTERNAL_PROVIDERS=true" in message


def test_llm_client_refuses_to_build_for_a_remote_endpoint():
    from app.generation.llm import LLM

    with pytest.raises(RuntimeError, match="ALLOW_EXTERNAL_PROVIDERS"):
        LLM(_settings(llm_base_url="https://integrate.api.nvidia.com/v1"))


def test_embedder_refuses_to_build_for_a_remote_endpoint():
    from app.retrieval.embed import get_embedder

    cfg = _settings(
        embed_provider="openai_compatible",
        embed_base_url="https://api.openai.com/v1",
        embed_api_key="sk-test",
    )
    with pytest.raises(RuntimeError, match="ALLOW_EXTERNAL_PROVIDERS"):
        get_embedder(cfg)


def test_external_providers_allowed_backcompat():
    cfg = _settings()
    assert cfg.external_providers_allowed("local") is True
    assert cfg.external_providers_allowed("none") is True
    with pytest.raises(RuntimeError):
        cfg.external_providers_allowed("openai_compatible", "https://api.x.ai/v1")


# --- shipped configuration --------------------------------------------------


def test_shipped_env_example_defaults_to_local():
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / ".env.example"
    cfg = Settings(_env_file=example)  # type: ignore[call-arg]
    assert cfg.allow_external_providers is False
    assert cfg.llm_is_local() is True
    assert cfg.embed_provider == "local"
    assert cfg.rerank_provider == "local"


def test_shipped_env_example_has_one_external_switch():
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / ".env.example"
    lines = [
        line.strip()
        for line in example.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("ALLOW_EXTERNAL_PROVIDERS=")
    ]
    assert len(lines) == 1, f"expected exactly one switch, found {lines}"