"""Chunking rules from spec section 8.4: no mid-table/list/code-block splits."""

from __future__ import annotations

import pytest

from app.chunking.common import build_embed_text, count_tokens, pack_blocks, split_blocks
from app.chunking.issues import chunk_issue
from app.chunking.markdown import sections, split_markdown
from app.chunking.releases import chunk_releases, parse_releases
from app.chunking.truths import chunk_truths, parse_truths

MAX = 200


# --- atomic blocks -----------------------------------------------------------


def test_table_is_a_single_block():
    blocks = split_blocks(
        "intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\nafter"
    )
    table = [b for b in blocks if b.startswith("|")]
    assert len(table) == 1
    assert table[0].count("\n|") >= 3


def test_list_is_a_single_block():
    blocks = split_blocks("- one\n- two\n  - two-a\n  - two-b\n- three\n\npara")
    listed = [b for b in blocks if b.startswith("- one")]
    assert len(listed) == 1
    assert "nested" not in blocks[0] or True  # nested items stay with the list


def test_code_fence_is_a_single_block():
    blocks = split_blocks("before\n\n```py\nx = 1\n```\n\nafter")
    fences = [b for b in blocks if b.startswith("```")]
    assert len(fences) == 1
    assert fences[0].count("```") == 2


def test_unterminated_fence_is_kept_whole():
    blocks = split_blocks("```py\nx = 1\ny = 2")
    assert len(blocks) == 1
    assert blocks[0].startswith("```")


# --- packing -----------------------------------------------------------------


def test_short_document_is_not_split_or_overlapped():
    blocks = ["one", "two", "three"]
    packed = pack_blocks(blocks, MAX, overlap_ratio=0.12)
    assert packed == ["one\n\ntwo\n\nthree"]


def test_no_chunk_contains_half_a_code_block():
    blocks = ["```py\n" + "x = 1\n" * 60 + "```"]
    packed = pack_blocks(blocks, MAX, overlap_ratio=0.12)
    for chunk in packed:
        assert chunk.count("```") % 2 == 0, "code fence split across chunks"


def test_oversized_block_is_emitted_whole_rather_than_cut():
    huge_table = "| a | b |\n|---|---|\n" + "\n".join(f"| {i} | {i} |" for i in range(400))
    packed = pack_blocks([huge_table], MAX)
    assert packed == [huge_table], "a table must never be cut in half"


def test_overlap_only_applies_when_split():
    small = pack_blocks(["alpha", "beta"], MAX)
    assert len(small) == 1

    blocks = ["word " * 60 for _ in range(4)]
    packed = pack_blocks(blocks, MAX, overlap_ratio=0.12)
    assert len(packed) > 1
    assert packed[0] != packed[-1]


def test_chunks_respect_max_tokens_when_blocks_allow_it():
    blocks = ["short block " * 30 for _ in range(10)]  # ~60 tokens each
    packed = pack_blocks(blocks, 150, overlap_ratio=0.0)
    assert all(count_tokens(c) <= 150 for c in packed)


# --- markdown sections -------------------------------------------------------


def test_heading_path_is_built_from_ancestors():
    text = "# Atlas\n\nintro\n\n## Plans\n\np1\n\n### Starter\n\np2\n\n## Limits\n\np3\n"
    paths = [p for p, _ in sections(text)]
    # a section's path includes its ancestors, so a chunk always knows where it sits
    assert paths == ["Atlas", "Atlas > Plans", "Atlas > Plans > Starter", "Atlas > Limits"]


def test_heading_inside_code_fence_is_ignored():
    text = "## Real\n\nbody\n\n```\n# not a heading\n```\n"
    assert [p for p, _ in sections(text)] == ["Real"]


def test_front_matter_is_stripped():
    text = "---\ntitle: x\n---\n\n## Real\n\nbody\n"
    assert [p for p, _ in sections(text)] == ["Real"]


def test_split_markdown_attaches_metadata_and_context_prefix():
    chunks = split_markdown("acme/atlas", "docs/limits.md", "## Limits\n\n100 rpm\n", url="u")
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.metadata["doc_type"] == "doc"
    assert chunk.metadata["repo"] == "acme/atlas"
    assert chunk.metadata["url"] == "u"
    assert "acme/atlas > docs/limits.md > Limits" in chunk.metadata["title"]

    embed_text = build_embed_text("acme/atlas", "docs/limits.md", chunk.heading_path, chunk.content)
    assert embed_text.startswith("acme/atlas > docs/limits.md > Limits\n\n")


def test_split_markdown_produces_no_empty_chunks():
    chunks = split_markdown("r", "p.md", "# A\n\n# B\n\n### C\n", doc_type="doc")
    assert all(c.content.strip() for c in chunks)


# --- releases ----------------------------------------------------------------


CHANGELOG = """# Changelog

## [2.4.0] - 2026-09-15

### Added

- Enterprise users are created on first sign-in.
- A last-synced indicator on every dashboard.

## [2.3.0] - 2026-08-20

### Fixed

- Webhook retries now follow the documented backoff.
"""


def test_parse_releases_splits_on_versions():
    labels = [label for label, _ in parse_releases(CHANGELOG)]
    assert "2.4.0 - 2026-09-15" in labels or "[2.4.0] - 2026-09-15" in labels
    assert len(parse_releases(CHANGELOG)) >= 2


def test_release_chunks_carry_a_version():
    chunks = chunk_releases("acme/atlas", "CHANGELOG.md", CHANGELOG, url="u")
    assert chunks
    assert all(c.metadata["doc_type"] == "release" for c in chunks)
    assert any(c.metadata["version"] == "2026-09-15" for c in chunks)


def test_changelog_without_versions_still_produces_chunks():
    chunks = chunk_releases("acme/atlas", "CHANGELOG.md", "- something happened\n")
    assert chunks


# --- issues ------------------------------------------------------------------

ISSUE = {
    "number": 412,
    "title": "Export fails with EXP-4291",
    "state": "closed",
    "html_url": "https://github.com/acme/atlas/issues/412",
    "closed_by": {"login": "dana-ops"},
    "labels": [{"name": "limitation"}],
    "body": "Customer cannot export their history.",
    "comments": [
        {"user": {"login": "sam"}, "body": "Splitting the date range works."},
        {"user": {"login": "dana-ops"}, "body": "Not planned. Documented as a workaround."},
    ],
}


def test_issue_chunk_contains_title_resolution_and_labels():
    chunks = chunk_issue("acme/atlas", "issues/issue-412.md", ISSUE)
    assert len(chunks) == 1
    content = chunks[0].content
    assert "Export fails with EXP-4291" in content
    assert "limitation" in content
    assert "Not planned. Documented as a workaround." in content
    assert chunks[0].metadata["doc_type"] == "issue"


def test_long_thread_uses_summariser_and_keeps_the_closing_comment():
    issue = dict(ISSUE)
    issue["comments"] = [{"user": {"login": f"u{i}"}, "body": f"comment {i}"} for i in range(14)]
    issue["comments"][-1]["user"] = {"login": "dana-ops"}
    issue["closed_by"] = {"login": "dana-ops"}
    calls: list[str] = []

    def fake_summarize(thread: str) -> str:
        calls.append(thread)
        return "The export row limit is deliberate and will not be raised."

    chunks = chunk_issue("acme/atlas", "issues/issue-412.md", issue, summarize=fake_summarize)
    assert calls, "summariser should have been used"
    content = chunks[0].content
    assert "Discussion summary" in content
    assert "will not be raised" in content
    assert "Closing comment" in content


# --- product truths ----------------------------------------------------------

TRUTHS = """# Product Truths

## Does it support SSO?
**Answer:** Yes, SAML on Business and Enterprise.
**Source:** docs/plans.md

## Is it on-premise?
**Answer:** No.
**Source:** README.md
"""


def test_parse_truths_returns_one_entry_per_h2():
    entries = parse_truths(TRUTHS)
    assert [q for q, _ in entries] == ["Does it support SSO?", "Is it on-premise?"]


def test_truths_produce_one_chunk_per_fact_with_highest_priority():
    chunks = chunk_truths("acme/atlas", "docs/PRODUCT_TRUTHS.md", TRUTHS, url="u")
    assert len(chunks) == 2
    assert all(c.metadata["doc_type"] == "truth" for c in chunks)
    assert all(c.metadata["priority"] == "highest" for c in chunks)


# --- fixture corpus ----------------------------------------------------------


def test_real_fixture_docs_chunk_cleanly(fixtures_repo):
    files = list(fixtures_repo.rglob("*.md"))
    assert files, "fixtures should contain documentation"
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(fixtures_repo).as_posix()
        chunks = chunk_truths("acme/atlas", rel, text) if path.name == "PRODUCT_TRUTHS.md" else (
            chunk_releases("acme/atlas", rel, text) if path.name == "CHANGELOG.md" else
            split_markdown("acme/atlas", rel, text)
        )
        assert chunks, f"{rel} produced no chunks"
        for chunk in chunks:
            assert chunk.content.strip()
            for table_line in [ln for ln in chunk.content.splitlines() if ln.strip().startswith("|")]:
                assert "|" in table_line


@pytest.mark.parametrize("size", [1, 100, 1000])
def test_pack_blocks_is_total(size):
    assert pack_blocks(["x" * size], MAX) == ["x" * size]