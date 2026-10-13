"""End-to-end ingestion: collect -> snapshot -> secret scan -> chunk -> embed -> upsert.

Run directly:  python -m app.ingestion.pipeline [--repo org/name]
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app import db
from app.chunking import (
    build_embed_text,
    chunk_issue,
    chunk_release_notes,
    chunk_releases,
    chunk_truths,
    content_hash,
    split_markdown,
)
from app.config import settings
from app.generation.llm import LLMUnavailable, get_llm
from app.ingestion import collector, mock_source
from app.ingestion.cleaners import clean_markdown, doc_kind
from app.ingestion.github_client import RawDoc
from app.ingestion.secret_scan import SecretScanError, scan_directory
from app.logging_ import store
from app.retrieval.embed import embed_text_vector, get_embedder

log = logging.getLogger(__name__)


# --- stage 1/2: collect and write a snapshot ---------------------------------


def collect(repo: str | None) -> list[RawDoc]:
    if settings.github_source == "github":
        repos = [repo] if repo else settings.github_repos
        if not repos:
            raise ValueError("GITHUB_SOURCE=github but GITHUB_REPOS is empty")
        docs: list[RawDoc] = []
        for name in repos:
            docs.extend(collector.collect_github(settings, name))
        return docs
    return mock_source.collect_mock(settings, repo or mock_source.MOCK_REPO)


def write_snapshot(docs: list[RawDoc], root: Path) -> None:
    """Materialise every document so gitleaks can scan exactly what we will index."""
    for doc in docs:
        target = root / doc.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.text, encoding="utf-8")


# --- stage 4: chunking -------------------------------------------------------


def _make_summarizer(enabled: bool):
    if not enabled:
        return None

    def summarize(thread: str) -> str:
        try:
            return get_llm().summarize(thread)
        except LLMUnavailable as exc:
            # Long threads stay truncated rather than failing the whole ingest.
            log.warning("thread summarisation failed, keeping raw comments: %s", exc)
            return ""

    return summarize


def chunk_document(doc: RawDoc, summarize=None) -> list[dict]:
    # The collector has already classified the document; only fall back to path
    # analysis for kinds that the file walk did not see (synthetic issue/release
    # paths such as "issues/issue-412.md", which look like ordinary markdown).
    kind = doc.kind or doc_kind(doc.rel_path, index_code=settings.index_code)

    if kind == "truth":
        chunks = chunk_truths(doc.repo, doc.rel_path, clean_markdown(doc.text), url=doc.url)
    elif kind == "release":
        chunks = chunk_releases(doc.repo, doc.rel_path, clean_markdown(doc.text), url=doc.url)
    elif kind == "release_notes":
        chunks = chunk_release_notes(
            doc.repo,
            doc.rel_path,
            {
                "tag_name": Path(doc.rel_path).stem,
                "name": Path(doc.rel_path).stem,
                "body": doc.text,
                "html_url": doc.url,
                "published_at": doc.version or "",
            },
        )
    elif kind in ("issue", "pr"):
        if doc.issue is None:
            return []
        chunks = chunk_issue(doc.repo, doc.rel_path, doc.issue, doc_type=kind, summarize=summarize)
    else:
        chunks = split_markdown(
            doc.repo,
            doc.rel_path,
            clean_markdown(doc.text),
            doc_type=kind,
            max_tokens=settings.chunk_max_tokens,
            min_tokens=settings.chunk_min_tokens,
            overlap_ratio=settings.chunk_overlap_ratio,
            url=doc.url,
        )

    out = []
    for chunk in chunks:
        embed_text = build_embed_text(doc.repo, doc.rel_path, chunk.heading_path, chunk.content)
        out.append(
            {
                "repo": doc.repo,
                "path": doc.rel_path,
                "url": doc.url,
                "doc_type": chunk.metadata.get("doc_type", kind),
                "heading_path": chunk.heading_path,
                "content": chunk.content,
                "embed_text": embed_text,
                "version": doc.version or chunk.metadata.get("version"),
                "updated_at": doc.updated_at,
                "content_hash": content_hash(embed_text),
            }
        )
    return out


# --- stage 5: upsert ---------------------------------------------------------

_UPSERT = """
INSERT INTO chunks (repo, path, url, doc_type, heading_path, content, embed_text,
                    embedding, version, updated_at, status, content_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, 'current', %s)
ON CONFLICT (repo, path, heading_path, content_hash) DO UPDATE
SET content = EXCLUDED.content,
    embed_text = EXCLUDED.embed_text,
    embedding = EXCLUDED.embedding,
    url = EXCLUDED.url,
    version = EXCLUDED.version,
    updated_at = EXCLUDED.updated_at,
    status = 'current',
    indexed_at = now()
"""


def _chunk_key(row: dict) -> tuple:
    return (row["repo"], row["path"], row["heading_path"], row["content_hash"])


def _existing_keys(rows: list[dict]) -> set[tuple]:
    """(repo, path, heading_path, content_hash) of chunks already indexed as current."""
    values = ",".join(["(%s,%s,%s,%s)"] * len(rows))
    params = [part for row in rows for part in _chunk_key(row)]
    found = db.query(
        f"SELECT repo, path, heading_path, content_hash FROM chunks "
        f"WHERE status = 'current' AND (repo, path, heading_path, content_hash) IN (VALUES {values})",
        params,
    )
    return {(r["repo"], r["path"], r["heading_path"], r["content_hash"]) for r in found}


def embed_and_store(rows: list[dict]) -> int:
    """Embed and upsert. Unchanged chunks are skipped (spec 8.5); their freshness
    metadata is still refreshed so the recency boost stays honest."""
    if not rows:
        return 0

    already = _existing_keys(rows)
    pending = [r for r in rows if _chunk_key(r) not in already]

    if already:
        with db.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "UPDATE chunks SET updated_at = %s, version = %s, status = 'current' "
                "WHERE repo = %s AND path = %s AND heading_path = %s AND content_hash = %s",
                [
                    (r["updated_at"], r["version"], r["repo"], r["path"],
                     r["heading_path"], r["content_hash"])
                    for r in rows if _chunk_key(r) in already
                ],
            )

    written = 0
    if pending:
        embedder = get_embedder()
        vectors = embedder.embed_documents([r["embed_text"] for r in pending])
        payload = [
            (
                r["repo"], r["path"], r["url"], r["doc_type"], r["heading_path"], r["content"],
                r["embed_text"], embed_text_vector(vector), r["version"], r["updated_at"],
                r["content_hash"],
            )
            for r, vector in zip(pending, vectors, strict=True)
        ]
        with db.connection() as conn, conn.cursor() as cur:
            cur.executemany(_UPSERT, payload)
        written = len(payload)

    log.info("indexed %d new chunks, skipped %d unchanged", written, len(already))
    return written + len(already)


def deprecate_missing(repo: str, seen_hashes: set[str]) -> int:
    """Mark chunks of files that no longer exist as deprecated; never delete (8.4)."""
    rows = db.query(
        "SELECT DISTINCT content_hash FROM chunks WHERE repo = %s AND status = 'current'",
        (repo,),
    )
    stale = {r["content_hash"] for r in rows} - seen_hashes
    if not stale:
        return 0
    return db.execute(
        "UPDATE chunks SET status = 'deprecated' WHERE repo = %s AND status = 'current' "
        "AND content_hash = ANY(%s)",
        (repo, list(stale)),
    )


# --- orchestration -----------------------------------------------------------


def ingest(repo: str | None = None) -> dict:
    run_id = store.start_ingest_run(repo)
    counts = {
        "files_seen": 0, "files_indexed": 0, "files_skipped_secrets": 0,
        "chunks_written": 0, "chunks_deprecated": 0,
    }
    try:
        docs = collect(repo)
        counts["files_seen"] = len(docs)

        # 1-2. snapshot, then 3. the mandatory secret scan (raises rather than
        #      indexing unscanned content). The snapshot is deleted on exit.
        with tempfile.TemporaryDirectory(prefix="prodex-ingest-") as tmp:
            root = Path(tmp)
            write_snapshot(docs, root)
            blocked = scan_directory(root)
            log.info("secret scan blocked %d of %d files", len(blocked), len(docs))

            kept = [d for d in docs if d.rel_path not in blocked]
            counts["files_skipped_secrets"] = len(docs) - len(kept)
            counts["files_indexed"] = len(kept)

            summarize = _make_summarizer(settings.summarize_issue_threads)
            rows: list[dict] = []
            for doc in kept:
                rows.extend(chunk_document(doc, summarize=summarize))

        # 5. embed + upsert (unchanged chunks are skipped by the content_hash conflict)
        counts["chunks_written"] = embed_and_store(rows)

        # 8.4. deprecate chunks whose source file no longer exists, per repo
        for target_repo, repo_rows in _group_by_repo(rows).items():
            counts["chunks_deprecated"] += deprecate_missing(
                target_repo, {r["content_hash"] for r in repo_rows}
            )

        version = store.touch_docs_version()
        store.purge_stale_cache(version)
        store.finish_ingest_run(run_id, status="success", **counts)
        log.info("ingest run %s done: %s", run_id, counts)
        return {"run_id": run_id, "repo": repo, **counts}

    except SecretScanError as exc:
        store.finish_ingest_run(run_id, status="failed", error=str(exc), **counts)
        raise
    except Exception as exc:
        store.finish_ingest_run(run_id, status="failed", error=str(exc), **counts)
        raise


def _group_by_repo(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["repo"], []).append(row)
    return grouped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest product documentation")
    parser.add_argument("--repo", default=None, help="limit to one repo (github source only)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        db.apply_schema()
        result = ingest(args.repo)
    except Exception as exc:
        log.error("ingest failed: %s", exc)
        return 1

    print(f"\nIngest complete: {result}\nDocs version: {store.docs_version()}")
    print(f"Corpus: {store.corpus_stats()} at {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())