"""Show exactly what the ingester would pick up from each allow-listed repo.

    docker compose run --rm api python eval/what_will_be_indexed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.ingestion.cleaners import doc_kind  # noqa: E402
from app.ingestion.github_client import GitHubClient  # noqa: E402


def main() -> int:
    client = GitHubClient(
        app_id=settings.github_app_id,
        installation_id=settings.github_app_installation_id,
        private_key_path=settings.github_private_key_path,
        token=settings.github_token,
        branch=settings.github_branch,
    )
    grand_total = 0
    try:
        for repo in settings.github_repos:
            entries = client.list_tree(repo)
            indexed = [e for e in entries if doc_kind(e["path"])]
            print("=" * 62)
            print(f"{repo}  ({len(entries)} files on {settings.github_branch})")
            print("=" * 62)
            if not entries:
                print("  branch not found, or the repo is empty")
                continue
            for entry in sorted(entries, key=lambda e: e["path"]):
                path = entry["path"]
                kind = doc_kind(path)
                mark = f"[{kind}]" if kind else "  .  "
                print(f"  {mark:<11} {path}")
            print(f"\n  -> {len(indexed)} of {len(entries)} files would be indexed")
            grand_total += len(indexed)
    finally:
        client.close()

    print("=" * 62)
    print(f"TOTAL indexable files: {grand_total}")
    if grand_total == 0:
        print("Nothing to index. Either the repos have no .md documentation, or")
        print("the branch name in GITHUB_BRANCH is wrong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())