"""Issue / PR chunking (spec section 8.4): title + description + resolution + key comments.

Long threads (> COMMENT_SUMMARY_THRESHOLD comments) are reduced to an LLM summary
plus the resolution comment; the summariser is injected so this module stays testable.
"""

from __future__ import annotations

from app.chunking.common import Chunk, context_prefix, dedupe_by_size, pack_blocks, split_blocks

COMMENT_SUMMARY_THRESHOLD = 10


def _comment_text(comment: dict) -> str:
    user = comment.get("user") or {}
    return f"- @{user.get('login', 'unknown')}: {(comment.get('body') or '').strip()}"


def _resolution_comment(issue: dict) -> dict | None:
    """Prefer the closing comment referenced by closed_by, else the last real comment."""
    closed_by = issue.get("closed_by")
    if closed_by:
        for c in reversed(issue.get("comments", [])):
            if (c.get("user") or {}).get("login") == closed_by:
                return c
    for c in reversed(issue.get("comments", [])):
        return c
    return None


def chunk_issue(
    repo: str,
    path: str,
    issue: dict,
    *,
    doc_type: str | None = None,
    max_tokens: int = 500,
    min_tokens: int = 100,
    summarize=None,
) -> list[Chunk]:
    """`summarize(thread_text) -> str` may be None; without it the thread is truncated."""
    number = issue.get("number")
    url = issue.get("html_url") or f"https://github.com/{repo}/issues/{number}"
    is_pr = bool(issue.get("pull_request")) or doc_type == "pr"
    kind = doc_type or ("pr" if is_pr else "issue")
    labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]

    title = (issue.get("title") or "").strip()
    body = (issue.get("body") or "").strip()
    state = issue.get("state", "")
    header = (
        f"# {title}\n"
        f"{kind.title()} #{number} | {state}"
        + (f" | labels: {', '.join(labels)}" if labels else "")
        + f"\nURL: {url}\n"
    )

    parts = [header]
    if body:
        parts.append(body)

    comments = issue.get("comments", [])
    resolution = _resolution_comment(issue)
    if len(comments) > COMMENT_SUMMARY_THRESHOLD and callable(summarize):
        thread = "\n".join(_comment_text(c) for c in comments)
        summary = summarize(f"{title}\n\n{thread}")
        parts.append("## Discussion summary\n" + (summary or "").strip())
        if resolution:
            parts.append("## Closing comment\n" + (resolution.get("body") or "").strip())
    elif comments:
        key = [c for c in comments if c is not resolution][:6]
        if key:
            parts.append("## Comments\n" + "\n".join(_comment_text(c) for c in key))
        if resolution is not None and resolution not in key:
            parts.append("## Closing comment\n" + (resolution.get("body") or "").strip())

    text = "\n\n".join(p for p in parts if p.strip())
    pieces = dedupe_by_size(pack_blocks(split_blocks(text), max_tokens), min_tokens)

    heading_path = f"{kind.title()} #{number}: {title}"
    return [
        Chunk(
            content=piece,
            heading_path=heading_path,
            metadata={
                "repo": repo,
                "path": path,
                "url": url,
                "doc_type": kind,
                "version": None,
                "title": f"{context_prefix(repo, path, heading_path)}",
            },
        )
        for piece in pieces
    ]