"""Release / changelog chunking (spec section 8.4): one chunk per release or feature entry."""

from __future__ import annotations

import re

from app.chunking.common import (
    Chunk,
    context_prefix,
    count_tokens,
    dedupe_by_size,
    pack_blocks,
    split_blocks,
)

# A release boundary is an H1-H3 heading that carries a version (`2.4.0`, `v2.4`)
# or is the conventional `[Unreleased]` placeholder. Matches `## [2.4.0] - 2026-09-15`,
# `## v2.4.0 (2026-09-15)`, `## Release 2.4.0` and `## 2.4.0`.
_VERSION_TOKEN = r"(?:\d{4}-\d{2}-\d{2}|v?\d+\.\d+(?:\.\d+)?)"
_RELEASE_HEADING = re.compile(rf"^#{{1,3}}\s+.*(?:{_VERSION_TOKEN}|unreleased).*$", re.IGNORECASE)
_SECTION_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_DATE_IN_HEADING = re.compile(r"(\d{4}-\d{2}-\d{2})")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_INDENTED = re.compile(r"^\s{2,}\S")


def parse_releases(text: str) -> list[tuple[str, str]]:
    """Return [(version_label, release_body)] from a CHANGELOG-style document."""
    lines = text.splitlines()
    starts: list[tuple[int, str]] = []
    in_fence = False
    fence = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if not in_fence:
                in_fence, fence = True, stripped[:3]
            elif stripped.startswith(fence):
                in_fence = False
            continue
        if in_fence:
            continue
        m = _SECTION_HEADING.match(line)
        if m and _RELEASE_HEADING.match(line):
            starts.append((idx, m.group(2).strip()))

    if not starts:
        return [("", text.strip())] if text.strip() else []

    out: list[tuple[str, str]] = []
    preamble = "\n".join(lines[: starts[0][0]]).strip()
    if preamble:
        out.append(("", preamble))
    for i, (start, label) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        if body:
            out.append((label, body))
    return out


def _version_of(label: str) -> str | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", label)
    if m:
        return m.group(1)
    return None


def _entries(body: str) -> list[str]:
    """Group a release body into feature entries, keeping prose and sub-headings whole."""
    groups: list[str] = []
    current: list[str] = []
    in_list = False

    def flush() -> None:
        nonlocal current, in_list
        if current:
            groups.append("\n".join(current).rstrip())
        current, in_list = [], False

    for line in body.splitlines():
        if not line.strip():
            continue
        if _LIST_ITEM.match(line):
            if current and not in_list:
                flush()
            in_list = True
            current.append(line)
        elif in_list and _INDENTED.match(line):
            current.append(line)  # continuation of the entry above
        else:
            flush()  # prose line or sub-heading starts its own group
            current.append(line)
    flush()
    return groups


def chunk_releases(
    repo: str,
    path: str,
    text: str,
    *,
    url: str = "",
    max_tokens: int = 400,
    min_tokens: int = 80,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for label, body in parse_releases(text):
        version = _version_of(label)
        # one chunk per release when it fits, otherwise one chunk per feature entry
        if count_tokens(body) <= max_tokens:
            pieces = [body]
        else:
            heading = body.splitlines()[0].strip()
            pieces = []
            for entry in _entries(body):
                pieces.extend(pack_blocks(split_blocks(f"{heading}\n\n{entry}"), max_tokens))
        pieces = dedupe_by_size(pieces, min_tokens)
        for piece in pieces:
            heading_path = f"Release {label}".strip() if label else "Release notes"
            chunks.append(
                Chunk(
                    content=piece,
                    heading_path=heading_path,
                    metadata={
                        "repo": repo,
                        "path": path,
                        "url": url,
                        "doc_type": "release",
                        "version": version,
                        "title": f"{context_prefix(repo, path, heading_path)}",
                    },
                )
            )
    return chunks


def chunk_release_notes(repo: str, path: str, release: dict, *, max_tokens: int = 400) -> list[Chunk]:
    """Chunk a GitHub Release object (name/tag + body)."""
    tag = release.get("tag_name") or release.get("name") or "release"
    url = release.get("html_url", "")
    published = (release.get("published_at") or "")[:10]
    body = (release.get("body") or "").strip()
    text = f"# {release.get('name') or tag}\nPublished: {published or 'unknown'}\n\n{body}"
    heading_path = f"Release {tag}"
    pieces = dedupe_by_size(pack_blocks(split_blocks(text), max_tokens), 80)
    return [
        Chunk(
            content=piece,
            heading_path=heading_path,
            metadata={
                "repo": repo,
                "path": path,
                "url": url,
                "doc_type": "release",
                "version": published or tag,
                "title": f"{context_prefix(repo, path, heading_path)}",
            },
        )
        for piece in pieces
    ]