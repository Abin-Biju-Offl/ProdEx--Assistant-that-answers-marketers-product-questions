"""Chunking package: every chunker returns `list[Chunk]` with full metadata."""

from app.chunking.common import Chunk, build_embed_text, content_hash, count_tokens
from app.chunking.issues import chunk_issue
from app.chunking.markdown import sections, split_markdown
from app.chunking.releases import chunk_release_notes, chunk_releases, parse_releases
from app.chunking.truths import chunk_truths, is_truths_doc

__all__ = [
    "Chunk",
    "build_embed_text",
    "chunk_issue",
    "chunk_release_notes",
    "chunk_releases",
    "chunk_truths",
    "content_hash",
    "count_tokens",
    "is_truths_doc",
    "parse_releases",
    "sections",
    "split_markdown",
]