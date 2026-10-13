"""Read-only GitHub App client (spec sections 6, 14.1).

Auth: GitHub App installation token, minted on demand from the app private key.
The token is short-lived and cached only in memory. The App should be installed on
the allow-listed repositories only and have read-only permissions.

Dev-only fallback: GITHUB_TOKEN (a classic PAT) so the pipeline can be exercised
before the App exists. See docs/DECISIONS.md.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import jwt

log = logging.getLogger(__name__)

API = "https://api.github.com"
JWT_LIFETIME = 540  # GitHub allows max 10 minutes; 9 keeps us clear of the edge


@dataclass
class RawDoc:
    """One fetched document, before cleaning, scanning and chunking.

    `rel_path` is the path inside the snapshot directory that gets written to disk
    and handed to gitleaks; it is also the chunk's `path` metadata.
    """

    repo: str
    rel_path: str
    kind: str  # readme|doc|release|adr|truth|code
    text: str
    url: str
    updated_at: datetime
    version: str | None = None
    issue: dict | None = None  # structured payload for issue/pr chunking
    extra: dict = field(default_factory=dict)


class GitHubAuthError(RuntimeError):
    pass


class GitHubClient:
    def __init__(
        self,
        app_id: str = "",
        installation_id: str = "",
        private_key_path: Path | None = None,
        token: str = "",
        branch: str = "main",
        timeout: float = 30.0,
    ) -> None:
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key_path = private_key_path
        self.static_token = token
        self.branch = branch
        self._client = httpx.Client(
            base_url=API,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # --- auth ---------------------------------------------------------------

    def _app_jwt(self) -> str:
        if not self.private_key_path or not Path(self.private_key_path).exists():
            raise GitHubAuthError(f"GitHub App private key not found at {self.private_key_path}")
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + JWT_LIFETIME, "iss": self.app_id}
        return jwt.encode(payload, Path(self.private_key_path).read_text(encoding="utf-8"), algorithm="RS256")

    def token(self) -> str:
        if self.static_token:
            return self.static_token
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        if not (self.app_id and self.installation_id):
            raise GitHubAuthError(
                "GitHub auth is not configured. Set GITHUB_APP_ID, "
                "GITHUB_APP_INSTALLATION_ID and GITHUB_PRIVATE_KEY_PATH, or set "
                "GITHUB_TOKEN for local development."
            )
        r = self._client.post(
            f"/app/installations/{self.installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self._app_jwt()}"},
        )
        if r.status_code >= 400:
            raise GitHubAuthError(f"could not mint installation token: {r.status_code} {r.text[:200]}")
        data = r.json()
        self._token = data["token"]
        self._token_expires_at = time.time() + float(data.get("expires_at_epoch", time.time() + 3600))
        return self._token

    # --- requests -----------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self._client.get(path, params=params, headers={"Authorization": f"Bearer {self.token()}"})
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub GET {path} failed: {r.status_code} {r.text[:300]}")
        return r.json()

    def _paginate(self, path: str, params: dict | None = None, limit: int = 200) -> Iterator[dict]:
        params = {**(params or {}), "per_page": 100}
        for page in range(1, limit + 1):
            data = self._get(path, {**params, "page": page})
            if not data:
                return
            yield from data
            if len(data) < 100:
                return

    def close(self) -> None:
        self._client.close()

    # --- content ------------------------------------------------------------

    def blob_url(self, repo: str, path: str, ref: str | None = None) -> str:
        ref = ref or self.branch
        return f"https://github.com/{repo}/blob/{ref}/{path}"

    def list_tree(self, repo: str, ref: str | None = None) -> list[dict]:
        """Recursive git tree (blobs only, no file contents)."""
        ref = ref or self.branch
        base = self._get(f"/repos/{repo}/git/trees/{ref}", {"recursive": "1"})
        if not base:
            return []
        if base.get("truncated"):
            log.warning("git tree for %s@%s was truncated by GitHub", repo, ref)
        return [t for t in base.get("tree", []) if t.get("type") == "blob"]

    def get_file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        import base64

        data = self._get(f"/repos/{repo}/contents/{path}", {"ref": ref or self.branch})
        if not data or data.get("type") != "file":
            return None
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", "")

    def list_releases(self, repo: str) -> list[dict]:
        return list(self._paginate(f"/repos/{repo}/releases", {"per_page": 100}))

    def list_closed_issues(self, repo: str, labels: list[str] | None = None) -> list[dict]:
        params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100}
        return [i for i in self._paginate(f"/repos/{repo}/issues", params) if "pull_request" not in i]

    def list_merged_pull_requests(self, repo: str) -> list[dict]:
        items = list(self._paginate(f"/repos/{repo}/pulls", {"state": "closed", "per_page": 100}))
        return [p for p in items if p.get("merged_at")]

    def issue_comments(self, repo: str, number: int) -> list[dict]:
        return list(self._paginate(f"/repos/{repo}/issues/{number}/comments", {"per_page": 100}, limit=5))

    def pull_request_files(self, repo: str, number: int) -> list[dict]:
        return list(self._paginate(f"/repos/{repo}/pulls/{number}/files", {"per_page": 100}, limit=5))

    def last_commit_date(self, repo: str) -> datetime:
        """Used as `updated_at` for every file; a per-file mtime would cost N API calls."""
        data = self._get(f"/repos/{repo}/commits", {"sha": self.branch, "per_page": 1})
        if data:
            stamp = (data[0].get("commit", {}).get("committer", {}) or {}).get("date")
            if stamp:
                return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return datetime.now(UTC)