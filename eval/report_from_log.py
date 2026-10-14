#!/usr/bin/env python
"""Rebuild the evaluation report from the requests log.

The eval runs in a throwaway container, so its JSON report disappears with it. This
re-scores whatever is already in the `requests` table, which means you can re-tune the
metrics without paying for the LLM again.

    docker compose run --rm api python eval/report_from_log.py --user U-EVAL-HARNESS
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.generation.answer import is_refusal  # noqa: E402
from eval.run_eval import load_questions, must_include_hit, print_report, summarise  # noqa: E402


def fetch_results(user_id: str) -> dict[str, dict]:
    """Latest logged request per question, with the sources it cited."""
    rows = db.query(
        "SELECT DISTINCT ON (question) id, question, answer, answered, top_score, "
        "       latency_ms, created_at, chunk_ids "
        "FROM requests WHERE slack_user_id = %s ORDER BY question, id DESC",
        (user_id,),
    )
    out = {}
    for row in rows:
        urls = []
        if row["chunk_ids"]:
            chunks = db.query(
                "SELECT url, repo, path, heading_path, updated_at FROM chunks "
                "WHERE id = ANY(%s) ORDER BY array_position(%s, id)",
                (list(row["chunk_ids"]), list(row["chunk_ids"])),
            )
            urls = [
                {
                    "n": i,
                    "title": " > ".join(
                        p for p in (c["repo"], c["path"], c["heading_path"]) if p
                    ),
                    "url": c["url"],
                    "updated_at": c["updated_at"].strftime("%Y-%m-%d"),
                }
                for i, c in enumerate(chunks, start=1)
            ]
        out[row["question"]] = {**row, "sources": urls}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-score the evaluation from the request log")
    parser.add_argument("--questions", default=str(Path(__file__).parent / "questions.yaml"))
    parser.add_argument("--user", default="U-EVAL-HARNESS", help="slack_user_id the eval used")
    args = parser.parse_args(argv)

    questions = load_questions(Path(args.questions))
    logged = fetch_results(args.user)

    missing = [q["q"] for q in questions if q["q"] not in logged]
    results = []
    for item in questions:
        row = logged.get(item["q"])
        if row is None:
            continue
        refusal = is_refusal(row["answer"] or "")
        hit = (
            any(
                item.get("expected_source", "").lower() in (s["title"] or "").lower()
                for s in row["sources"]
            )
            if item.get("expected_source")
            else None
        )
        response = type(
            "R", (), {"answer": row["answer"], "answered": row["answered"], "sources": row["sources"]}
        )()
        correct = _judge(response, item, refusal, hit)
        results.append(
            {
                "q": item["q"],
                "should_answer": item["should_answer"],
                "answered": row["answered"],
                "refusal": refusal,
                "correct": correct,
                "confidently_wrong": (row["answered"] and not correct)
                or (not item["should_answer"] and not refusal),
                "retrieval_hit": hit,
                "latency_ms": row["latency_ms"] or 0,
                "answer": row["answer"] or "",
                "sources": [s["url"] for s in row["sources"]],
            }
        )

    if missing:
        print(f"WARNING: {len(missing)} questions have no logged result and were skipped:")
        for q in missing[:5]:
            print(f"  - {q}")

    report = summarise(results)
    print(f"Scored {report['total']} logged results for user {args.user}\n")
    print_report(report)
    return 0


def _judge(response, item: dict, refusal: bool, hit: bool | None) -> bool:
    if not item["should_answer"]:
        return not response.answered and (
            refusal or "not in the docs" in response.answer.lower()
        )
    if not response.answered or refusal:
        return False
    return must_include_hit(response, item.get("must_include", [])) and hit is not False


if __name__ == "__main__":
    sys.exit(main())