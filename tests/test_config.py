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


def test_shipped_env_example_parses():
    """The .env we tell users to copy must actually load."""
    from pathlib import Path

    from app.config import Settings

    example = Path(__file__).resolve().parent.parent / ".env.example"
    for key in ("GITHUB_REPOS", "SLACK_ALLOWED_CHANNELS"):
        os.environ.pop(key, None)
    s = Settings(_env_file=example)  # type: ignore[call-arg]
    assert s.github_repos == ["acme/prodex-core", "acme/prodex-docs"]
    assert s.github_source == "mock"
    assert s.llm_model == "qwen2.5:7b-instruct"
    assert s.allow_external_providers is False


def test_external_provider_is_refused_by_default():
    from app.config import Settings

    os.environ.pop("ALLOW_EXTERNAL_PROVIDERS", None)
    s = Settings()
    assert s.external_providers_allowed("local") is True
    try:
        s.external_providers_allowed("openai")
    except RuntimeError as exc:
        assert "ALLOW_EXTERNAL_PROVIDERS" in str(exc)
    else:
        raise AssertionError("openai must be refused while ALLOW_EXTERNAL_PROVIDERS=false")