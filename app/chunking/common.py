"""Shared chunking primitives: token counting, context prefix, atomic blocks.

Rules from spec section 8.4:
  * never split inside a table, list, or code block
  * overlap 10-15% only when a section exceeds the max size and must be split
  * prepend `Repo > File > Heading path` to the embedding text
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

import tiktoken

_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_LIST_RE = re.compile(r"^\s*([-*+]\s+|\d+[.)]\s+)")
_INDENTED_RE = re.compile(r"^\s{2,}\S")
_TABLE_RE = re.compile(r"^\s*\|")
_TABLE_FILLER_RE = re.compile(r"^[\s:\-]*\|[\s|:\-]*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


# --- tokens -----------------------------------------------------------------


@lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- chunk record -----------------------------------------------------------


@dataclass
class Chunk:
    """One indexable unit. `content` is shown to the LLM; `embed_text` is indexed."""

    content: str
    heading_path: str = ""
    metadata: dict = field(default_factory=dict)


def context_prefix(repo: str, path: str, heading_path: str) -> str:
    parts = [repo, path]
    if heading_path:
        parts.append(heading_path)
    return " > ".join(parts)


def build_embed_text(repo: str, path: str, heading_path: str, content: str) -> str:
    return f"{context_prefix(repo, path, heading_path)}\n\n{content}"


# --- markdown block splitting ----------------------------------------------

def _is_blank(line: str) -> bool:
    return not line.strip()


def _fence_marker(line: str) -> str | None:
    m = _FENCE_RE.match(line)
    return m.group(1)[:3] if m else None


def split_blocks(text: str) -> list[str]:
    """Break markdown into blocks that must never be split internally.

    Fenced code blocks, tables and lists are each returned as one block. Anything
    else is grouped into paragraph blocks. Headings stand alone.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]

        if _is_blank(line):
            i += 1
            continue

        # fenced code block, possibly unterminated -> keep whole either way
        marker = _fence_marker(line)
        if marker:
            block = [line]
            i += 1
            while i < n:
                block.append(lines[i])
                i += 1
                if lines[i - 1].strip().startswith(marker):
                    break
            blocks.append("\n".join(block))
            continue

        if _HEADING_RE.match(line):
            blocks.append(line.strip())
            i += 1
            continue

        if _TABLE_RE.match(line):
            block = []
            while i < n and (_TABLE_RE.match(lines[i]) or (block and _TABLE_FILLER_RE.match(lines[i]))):
                block.append(lines[i])
                i += 1
            blocks.append("\n".join(block).strip())
            continue

        if _LIST_RE.match(line):
            block = []
            while i < n:
                cur = lines[i]
                nxt = lines[i + 1] if i + 1 < n else None
                nxt_continues = nxt is not None and (_LIST_RE.match(nxt) or _INDENTED_RE.match(nxt))
                continues = (
                    _LIST_RE.match(cur)
                    or _INDENTED_RE.match(cur)
                    or (_is_blank(cur) and nxt_continues)
                )
                if not continues:
                    break
                block.append(cur)
                i += 1
            blocks.append("\n".join(block).rstrip())
            continue

        # paragraph
        block = []
        while (
            i < n
            and not _is_blank(lines[i])
            and not _fence_marker(lines[i])
            and not _HEADING_RE.match(lines[i])
            and not _TABLE_RE.match(lines[i])
            and not _LIST_RE.match(lines[i])
        ):
            block.append(lines[i])
            i += 1
        blocks.append("\n".join(block).strip())

    return [b for b in blocks if b.strip()]


# --- packing ----------------------------------------------------------------


def pack_blocks(
    blocks: list[str],
    max_tokens: int,
    overlap_ratio: float = 0.12,
) -> list[str]:
    """Greedily pack atomic blocks into chunks of at most `max_tokens`.

    A block larger than `max_tokens` is emitted whole rather than cut, which keeps
    the "never split inside a table/list/code block" guarantee. Overlap is carried
    from the tail of one chunk into the next, and only when the section actually
    had to be split (spec section 8.4).
    """
    blocks = [b for b in blocks if b.strip()]
    if not blocks:
        return []

    sizes = [count_tokens(b) for b in blocks]
    if sum(sizes) <= max_tokens:
        return ["\n\n".join(blocks)]

    overlap_tokens = max(1, int(max_tokens * overlap_ratio))
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    i = 0

    while i < len(blocks):
        size = sizes[i]
        if size > max_tokens:
            if current:
                chunks.append("\n\n".join(current))
                current, current_tokens = [], 0
            chunks.append(blocks[i])
            i += 1
            continue

        if current and current_tokens + size > max_tokens:
            chunks.append("\n\n".join(current))
            carry: list[str] = []
            carry_tokens = 0
            for prev in reversed(current):
                prev_tokens = count_tokens(prev)
                if carry_tokens + prev_tokens > overlap_tokens:
                    break
                carry.insert(0, prev)
                carry_tokens += prev_tokens
            current, current_tokens = carry, carry_tokens

        current.append(blocks[i])
        current_tokens += size
        i += 1

    if current:
        chunks.append("\n\n".join(current))

    if len(chunks) > 1 and chunks[-1].strip() == chunks[-2].strip():
        chunks.pop()
    return chunks


def dedupe_by_size(chunks: list[str], min_tokens: int) -> list[str]:
    """Drop fragments too small to carry meaning, unless that empties the list."""
    kept = [c for c in chunks if count_tokens(c) >= min_tokens]
    return kept or chunks