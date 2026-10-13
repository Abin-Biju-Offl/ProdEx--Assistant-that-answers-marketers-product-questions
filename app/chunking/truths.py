"""Product Truths chunking (spec section 8.1): one chunk per fact or Q&A pair.

`docs/PRODUCT_TRUTHS.md` format (see the template in docs/PRODUCT_TRUTHS.md):

    ## Does the product support SSO?
    **Answer:** Yes, via SAML on the Business plan.
    **Source:** docs/auth.md
    **Owner:** platform-team

Every `## ` section is one hand-approved fact. These get the highest retrieval
boost, so the wording should stay short and unambiguous.
"""

from __future__ import annotations

import re

from app.chunking.common import (
    Chunk,
    context_prefix,
    dedupe_by_size,
    pack_blocks,
    split_blocks,
)

_TRUTH_HEADING = re.compile(r"^##\s+(.*\S)\s*$")


def parse_truths(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    out: list[tuple[str, str]] = []
    current: list[str] = []
    heading = ""
    for line in lines:
        m = _TRUTH_HEADING.match(line)
        if m:
            if heading and current:
                out.append((heading, "\n".join(current).strip()))
            heading, current = m.group(1).strip(), [line]
        elif heading:
            current.append(line)
        elif line.strip():
            heading, current = "", [line]
    if heading and current:
        out.append((heading, "\n".join(current).strip()))
    return [(h, b) for h, b in out if b.strip()]


def chunk_truths(
    repo: str,
    path: str,
    text: str,
    *,
    url: str = "",
    max_tokens: int = 200,
    min_tokens: int = 40,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for question, body in parse_truths(text):
        pieces = dedupe_by_size(pack_blocks(split_blocks(body), max_tokens), min_tokens)
        for piece in pieces:
            heading_path = question
            chunks.append(
                Chunk(
                    content=piece,
                    heading_path=heading_path,
                    metadata={
                        "repo": repo,
                        "path": path,
                        "url": url,
                        "doc_type": "truth",
                        "version": None,
                        "title": f"{context_prefix(repo, path, heading_path)}",
                        "priority": "highest",
                    },
                )
            )
    return chunks


def is_truths_doc(path: str) -> bool:
    return path.lower().endswith("product_truths.md")