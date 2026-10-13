"""Local fixture source, so the whole pipeline runs without GitHub credentials.

Mirrors the shape of `collect_github` exactly: the same files, the same issue and
release records, the same cleaning. Set GITHUB_SOURCE=github to use GitHub instead.

Layout of fixtures/repo:
    README.md, docs/**, CHANGELOG.md, adr/**.md   -> documentation files
    .mock/issues.json                              -> closed issues + merged PRs
    .mock/releases.json                            -> GitHub Releases
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.ingestion.cleaners import clean_comments, doc_kind
from app.ingestion.collector import render_issue_text
from app.ingestion.github_client import RawDoc

log = logging.getLogger(__name__)

MOCK_DIR = ".mock"
MOCK_REPO = "acme/prodex-core"


def _updated_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("items", [])


def collect_mock(settings: Settings, repo: str = MOCK_REPO) -> list[RawDoc]:
    root = Path(settings.fixtures_dir)
    if not root.exists():
        raise FileNotFoundError(
            f"fixtures not found at {root}. Run ingestion from the repo root "
            "or set FIXTURES_DIR in .env."
        )

    docs: list[RawDoc] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(f"{MOCK_DIR}/"):
            continue
        kind = doc_kind(rel, index_code=settings.index_code)
        if kind is None:
            continue
        if path.name.lower() == "product_truths.md":
            kind = "truth"
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        docs.append(
            RawDoc(
                repo=repo,
                rel_path=rel,
                kind=kind,
                text=text,
                url=f"https://github.com/{repo}/blob/main/{rel}",
                updated_at=_updated_at(path),
            )
        )

    for item in _load_json(root / MOCK_DIR / "issues.json"):
        item = dict(item)
        kind = "pr" if "pull_request" in item or item.get("kind") == "pr" else "issue"
        item.pop("kind", None)
        item["comments"] = clean_comments(item.get("comments", []))
        number = item.get("number")
        docs.append(
            RawDoc(
                repo=repo,
                rel_path=f"{kind}s/{kind}-{number}.md",
                kind=kind,
                text=render_issue_text(item),
                url=item.get("html_url", f"https://github.com/{repo}/issues/{number}"),
                updated_at=_updated_at(root / MOCK_DIR / "issues.json"),
                issue=item,
            )
        )

    for release in _load_json(root / MOCK_DIR / "releases.json"):
        body = (release.get("body") or "").strip()
        if not body:
            continue
        tag = release.get("tag_name") or "release"
        docs.append(
            RawDoc(
                repo=repo,
                rel_path=f"releases/{tag}.md",
                kind="release_notes",
                text=body,
                url=release.get("html_url", ""),
                updated_at=datetime.fromisoformat(
                    (release.get("published_at") or "2026-01-01")[:10]
                ).replace(tzinfo=UTC),
                version=(release.get("published_at") or "")[:10] or tag,
            )
        )

    log.info("collected %d documents from fixtures (%s)", len(docs), repo)
    return docs