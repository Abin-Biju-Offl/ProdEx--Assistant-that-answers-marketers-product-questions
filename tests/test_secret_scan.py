"""The gitleaks pre-index scan must block files and fail closed (spec 8.3, 14.3)."""

from __future__ import annotations

import shutil

import pytest

from app.ingestion.secret_scan import SecretScanError, gitleaks_available, scan_directory

pytestmark = pytest.mark.skipif(not gitleaks_available(), reason="gitleaks is not installed")

# A deliberately fake AWS example key. Never a real credential.
FAKE_SECRET = "docs/leaky.md:9: aws_access_key_id = 'AKIAIOSFODNN7EXAMPLE'\n"
CLEAN_DOC = "docs/guide.md\n\nAtlas syncs once a day at 03:00 UTC.\n"


@pytest.fixture
def snapshot(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(CLEAN_DOC, encoding="utf-8")
    (tmp_path / "docs" / "leaky.md").write_text(
        "# Deploy\n\nSet the key before running.\n\n```\naws_access_key_id = AKIAIOSFODNN7EXAMPLE\n"
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n```\n",
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
    for path in flagged:
        assert "AKIA" not in path
        assert "SECRET" not in path.upper()