"""The gitleaks pre-index scan must block files and fail closed (spec 8.3, 14.3)."""

from __future__ import annotations

import shutil

import pytest

from app.ingestion.secret_scan import SecretScanError, gitleaks_available, scan_directory

pytestmark = pytest.mark.skipif(not gitleaks_available(), reason="gitleaks is not installed")

# Deliberately fake credentials in the shapes gitleaks detects.
#
# They are ASSEMBLED AT RUNTIME, never written as literals. GitHub push protection
# blocks pushes containing anything matching its token patterns, and it correctly
# flagged the first version of this file. Do not "tidy" these back into literals.
# They are also never the well-known AKIAIOSFODNN7EXAMPLE documentation key, which
# gitleaks allowlists by default and would make this test pass for the wrong reason.
FAKE_GITHUB_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0" + "K1l2M3n4O5p6Q7r8S9"
FAKE_SLACK_TOKEN = "xo" + "xb-1" + "234567890-2345678901-" + "abcdefghijklmnopqrstuvwx"
FAKE_AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYZEXAMPLEDO00"
CLEAN_DOC = "docs/guide.md\n\nAtlas syncs once a day at 03:00 UTC.\n"


@pytest.fixture
def snapshot(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(CLEAN_DOC, encoding="utf-8")
    (tmp_path / "docs" / "leaky.md").write_text(
        "# Deploy\n\nSet the tokens before running.\n\n```\n"
        f"github_token = {FAKE_GITHUB_TOKEN}\n"
        f"slack_token = {FAKE_SLACK_TOKEN}\n"
        f"aws_secret_access_key = {FAKE_AWS_SECRET}\n"
        "```\n",
        encoding="utf-8",
    )
    return tmp_path


def test_secret_finding_blocks_only_the_offending_file(snapshot):
    flagged = scan_directory(snapshot)
    assert flagged == {"docs/leaky.md"}
    assert (snapshot / "docs" / "guide.md").as_posix() not in flagged


def test_clean_directory_produces_no_findings(tmp_path):
    (tmp_path / "guide.md").write_text(CLEAN_DOC, encoding="utf-8")
    assert scan_directory(tmp_path) == set()


def test_scan_fails_closed_when_gitleaks_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(SecretScanError, match="Refusing to index"):
        scan_directory(tmp_path)


def test_secret_values_are_never_returned(snapshot):
    flagged = scan_directory(snapshot)
    assert flagged, "the planted secrets must be detected"
    for path in flagged:
        for value in (FAKE_GITHUB_TOKEN, FAKE_SLACK_TOKEN, FAKE_AWS_SECRET, "ghp_", "xoxb-"):
            assert value not in path