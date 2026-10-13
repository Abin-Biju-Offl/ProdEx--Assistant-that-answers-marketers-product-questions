"""Mandatory gitleaks pre-index scan (spec sections 8.3, 14.3).

Fail closed:
  * gitleaks missing or erroring -> raise, nothing is indexed
  * any finding -> the offending file is blocked (the secret itself is never logged)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


class SecretScanError(RuntimeError):
    """Raised when the scan cannot be completed. Callers must not index."""


def gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


def scan_directory(root: Path) -> set[str]:
    """Run `gitleaks detect --no-git` over `root`.

    Returns the set of repo-relative file paths that contain a finding.
    Raises SecretScanError if the scan could not run.
    """
    if not gitleaks_available():
        raise SecretScanError(
            "gitleaks is not installed. Refusing to index (spec section 14.3). "
            "Install it or use the container image, which bundles it."
        )

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "gitleaks.json"
        cmd = [
            "gitleaks", "detect",
            "--no-git",
            "--source", str(root),
            "--report-format", "json",
            "--report-path", str(report),
            "--exit-code", "0",  # we decide what to do with findings
            "--redact",
            "--no-banner",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SecretScanError(f"gitleaks could not run: {exc}") from exc

        if proc.returncode != 0 and not report.exists():
            raise SecretScanError(
                f"gitleaks exited with {proc.returncode}: {proc.stderr.strip()[:400]}"
            )
        if not report.exists():
            return set()

        try:
            findings = json.loads(report.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError as exc:
            raise SecretScanError(f"unreadable gitleaks report: {exc}") from exc

    root_resolved = root.resolve()
    flagged: set[str] = set()
    for finding in findings:
        raw = finding.get("File") or finding.get("file") or ""
        try:
            relative = Path(raw).resolve().relative_to(root_resolved)
        except (ValueError, OSError):
            relative = Path(raw)
        # only the path is kept; the finding's secret value is never logged or stored
        flagged.add(relative.as_posix())
        log.warning("secret scan: blocking %s (rule %s)", relative.as_posix(),
                    finding.get("RuleID", "unknown"))
    return flagged