"""Markdown chunking: split on H2/H3, keep the heading path (spec section 8.4)."""

from __future__ import annotations

import re

from app.chunking.common import (
    Chunk,
    context_prefix,
    dedupe_by_size,
    pack_blocks,
    split_blocks,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return text


def sections(text: str) -> list[tuple[str, str]]:
    """Return [(heading_path, body)] for a markdown document.

    The heading line itself stays in the body so the LLM sees the section title.
    """
    lines = _strip_front_matter(text).splitlines()
    headings: list[tuple[int, int, str]] = []  # (level, line_no, title)
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
        m = _HEADING.match(line)
        if m:
            headings.append((len(m.group(1)), idx, m.group(2).strip()))

    out: list[tuple[str, str]] = []
    if not headings or headings[0][1] > 0:
        start = headings[0][1] if headings else 0
        preamble = "\n".join(lines[:start]).strip()
        if preamble:
            out.append(("", preamble))

    stack: list[tuple[int, str]] = []
    for i, (level, start, title) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        heading_path = " > ".join([t for _, t in stack] + [title])
        stack.append((level, title))
        end = headings[i + 1][1] if i + 1 < len(headings) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        if body:
            out.append((heading_path, body))
    return out


def split_markdown(
    repo: str,
    path: str,
    text: str,
    *,
    doc_type: str = "doc",
    max_tokens: int = 600,
    min_tokens: int = 100,
    overlap_ratio: float = 0.12,
    version: str | None = None,
    url: str = "",
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading_path, body in sections(text):
        pieces = pack_blocks(split_blocks(body), max_tokens, overlap_ratio)
        pieces = dedupe_by_size(pieces, min_tokens)
        for piece in pieces:
            chunks.append(
                Chunk(
                    content=piece,
                    heading_path=heading_path,
                    metadata={
                        "repo": repo,
                        "path": path,
                        "url": url,
                        "doc_type": doc_type,
                        "version": version,
                        "title": f"{context_prefix(repo, path, heading_path)}",
                    },
                )
            )
    return chunks