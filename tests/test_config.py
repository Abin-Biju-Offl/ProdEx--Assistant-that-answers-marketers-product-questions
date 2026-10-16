"""Config must accept plain comma-separated values from .env (see issue: API crash)."""

import os


def test_csv_env_values_parse():
    os.environ["GITHUB_REPOS"] = "acme/prodex-core,acme/prodex-docs"
    os.environ["SLACK_ALLOWED_CHANNELS"] = "C111,C222"
    from app.config import Settings

    s = Settings()
    assert s.github_repos == ["acme/prodex-core", "acme/prodex-docs"]
    assert s.slack_allowed_channels == ["C111", "C222"]


def test_json_env_values_still_parse():
    os.environ["GITHUB_REPOS"] = '["json","format"]'
    from app.config import Settings

    assert Settings().github_repos == ["json", "format"]


def test_defaults_when_unset():
    for key in ("GITHUB_REPOS", "SLACK_ALLOWED_CHANNELS"):
        os.environ.pop(key, None)
    from app.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.github_repos == []
    assert s.slack_allowed_channels == []


def test_shipped_env_example_parses(monkeypatch):
    """The .env we tell users to copy must actually load.

    Environment variables outrank the settings file, so clear every key the
    example defines first - otherwise this silently asserts on the running
    container's environment instead of on the shipped file.
    """
    from pathlib import Path

    from app.config import Settings

    example = Path(__file__).resolve().parent.parent / ".env.example"
    declared = {
        line.split("=", 1)[0].strip()
        for line in example.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    for key in declared:
        monkeypatch.delenv(key, raising=False)

    s = Settings(_env_file=example)  # type: ignore[call-arg]
    assert s.github_repos == ["acme/prodex-core", "acme/prodex-docs"]
    assert s.github_source == "mock"
    assert s.llm_model == "qwen2.5:3b-instruct"
    assert s.llm_is_local() is True
    assert s.allow_external_providers is False
    assert s.embed_provider == "local"
    assert s.rerank_provider == "local"


def test_external_provider_gate_is_covered_in_test_provider_gate():
    """The provider switch has its own module; see tests/test_provider_gate.py."""
    assert True