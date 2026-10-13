"""Collect documents from GitHub (spec section 8.1).

Only allow-listed repos on the configured branch are read, and only documentation
files are kept. Code is fetched only when INDEX_CODE=true.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.ingestion.cleaners import clean_comments, doc_kind, neutralize_instructions
from app.ingestion.github_client import GitHubClient, RawDoc

log = logging.getLogger(__name__)


def _label_names(labels: list) -> list[str]:
    return [label["name"] if isinstance(label, dict) else str(label) for label in labels or []]


def render_issue_text(issue: dict) -> str:
    """Plain-text snapshot of an issue/PR, used for the gitleaks scan."""
    lines = [
        f"# {issue.get('title', '')}",
        f"state={issue.get('state', '')} labels={_label_names(issue.get('labels', []))}",
        issue.get("body") or "",
    ]
    for comment in issue.get("comments", []):
        user = (comment.get("user") or {}).get("login", "unknown")
        lines.append(f"@{user}:\n{comment.get('body') or ''}")
    return "\n\n".join(lines)


def _prepare_issue(client: GitHubClient, repo: str, item: dict, kind: str) -> RawDoc | None:
    number = item.get("number")
    if kind == "issue":
        item = dict(item)
        item["comments"] = [
            {"user": c.get("user") or {}, "body": c.get("body") or ""}
            for c in client.issue_comments(repo, number)
        ]
    item = dict(item)
    item["labels"] = [{"name": name} for name in _label_names(item.get("labels", []))]
    item["comments"] = clean_comments(item.get("comments", []))
    body = neutralize_instructions(item.get("body") or "")
    item["body"] = body
    text = render_issue_text(item)
    return RawDoc(
        repo=repo,
        rel_path=f"{kind}s/{kind}-{number}.md",
        kind=kind,
        text=text,
        url=item.get("html_url", ""),
        updated_at=client.last_commit_date(repo),
        issue=item,
    )


def collect_github(settings: Settings, repo: str) -> list[RawDoc]:
    client = GitHubClient(
        app_id=settings.github_app_id,
        installation_id=settings.github_app_installation_id,
        private_key_path=settings.github_private_key_path,
        token=settings.github_token,
        branch=settings.github_branch,
    )
    docs: list[RawDoc] = []
    try:
        updated_at = client.last_commit_date(repo)
        for entry in client.list_tree(repo):
            path = entry.get("path", "")
            kind = doc_kind(path, index_code=settings.index_code)
            if kind is None:
                continue
            if path.lower().endswith("product_truths.md"):
                kind = "truth"
            text = client.get_file(repo, path)
            if not text:
                continue
            docs.append(
                RawDoc(
                    repo=repo,
                    rel_path=path,
                    kind=kind,
                    text=text,
                    url=client.blob_url(repo, path),
                    updated_at=updated_at,
                )
            )

        for release in client.list_releases(repo):
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
                    updated_at=updated_at,
                    version=(release.get("published_at") or "")[:10] or tag,
                )
            )

        for issue in client.list_closed_issues(repo):
            doc = _prepare_issue(client, repo, issue, "issue")
            if doc:
                docs.append(doc)

        for pr in client.list_merged_pull_requests(repo):
            doc = _prepare_issue(client, repo, pr, "pr")
            if doc:
                docs.append(doc)
    finally:
        client.close()

    log.info("collected %d documents from %s", len(docs), repo)
    return docs