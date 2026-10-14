#!/usr/bin/env python
"""Evaluation harness (spec section 12).

Reports the five numbers that matter:
  answer accuracy, correct-refusal rate, confident-wrong rate,
  p50/p95 latency, retrieval hit rate.

Run:  docker compose run --rm api python eval/run_eval.py
      docker compose run --rm api python eval/run_eval.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.generation.answer import answer_question, is_refusal  # noqa: E402
from app.logging_ import store  # noqa: E402
from app.models import AskRequest  # noqa: E402

EVAL_USER = "U-EVAL-HARNESS"


def load_questions(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) < 30:
        raise SystemExit(f"{path} must contain at least 30 questions (found {len(data or [])})")
    for i, item in enumerate(data, start=1):
        if "q" not in item or "should_answer" not in item:
            raise SystemExit(f"question {i} needs 'q' and 'should_answer'")
    return data


def source_hit(response, expected: str | None) -> bool | None:
    """True when a cited source is the expected one.

    Both sides are lowercased: paths are stored with their original case
    (docs/PRODUCT_TRUTHS.md), so a case-sensitive comparison silently fails.
    """
    if not expected:
        return None
    needle = expected.lower()
    return any(needle in (s.title or "").lower() for s in response.sources)


def must_include_hit(response, needles: list[str]) -> bool:
    if not needles:
        return True
    answer = (response.answer or "").lower()
    return all(needle.lower() in answer for needle in needles)


def evaluate(questions: list[dict], verbose: bool = True) -> dict:
    results: list[dict] = []

    for index, item in enumerate(questions, start=1):
        request = AskRequest(question=item["q"], slack_user_id=EVAL_USER, channel_type="dm")
        started = time.perf_counter()
        try:
            response = answer_question(request, use_cache=False)
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            results.append(
                {
                    "q": item["q"],
                    "should_answer": item["should_answer"],
                    "error": str(exc),
                    "latency_ms": elapsed,
                    "correct": False,
                    "confidently_wrong": item["should_answer"],
                    "retrieval_hit": None,
                    "answered": False,
                    "answer": "",
                    "sources": [],
                }
            )
            if verbose:
                print(f"[{index:>2}] ERROR  {item['q'][:70]}  ({exc})")
            continue

        latency_ms = (time.perf_counter() - started) * 1000
        hit = source_hit(response, item.get("expected_source"))
        refusal = is_refusal(response.answer)
        correct = _judge(response, item, refusal, hit)

        # Confident-wrong (spec 12): we ANSWERED and the answer was wrong, or we
        # answered a question that must be refused. A refusal on an answerable
        # question is a miss, not a confident error - counting it here would hide
        # which of the two failure modes we actually have.
        confidently_wrong = (response.answered and not correct) or (
            not item["should_answer"] and not refusal
        )

        results.append(
            {
                "q": item["q"],
                "should_answer": item["should_answer"],
                "answered": response.answered,
                "refusal": refusal,
                "correct": correct,
                "confidently_wrong": confidently_wrong,
                "retrieval_hit": hit,
                "latency_ms": latency_ms,
                "answer": response.answer,
                "sources": [s.url for s in response.sources],
            }
        )

        if verbose:
            mark = "PASS" if correct else ("WRONG" if response.answered else "refus")
            print(f"[{index:>2}] {mark:>5}  {item['q'][:66]:<66} {latency_ms:6.0f}ms")

    return summarise(results)


def _judge(response, item: dict, refusal: bool, hit: bool | None) -> bool:
    if not item["should_answer"]:
        return not response.answered and (refusal or "not in the docs" in response.answer.lower())
    if not response.answered or refusal:
        return False
    return must_include_hit(response, item.get("must_include", [])) and (hit is not False)


def summarise(results: list[dict]) -> dict:
    answerable = [r for r in results if r["should_answer"]]
    refusable = [r for r in results if not r["should_answer"]]
    latencies = sorted(r["latency_ms"] for r in results)
    hits = [r["retrieval_hit"] for r in results if r["retrieval_hit"] is not None]

    def pct(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, int(round(q * (len(values) - 1))))
        return values[index]

    return {
        "total": len(results),
        "answerable": len(answerable),
        "refusable": len(refusable),
        "errors": sum(1 for r in results if r.get("error")),
        "answer_accuracy": _ratio(sum(1 for r in answerable if r["correct"]), len(answerable)),
        "correct_refusal_rate": _ratio(sum(1 for r in refusable if r["correct"]), len(refusable)),
        "confident_wrong_rate": _ratio(sum(1 for r in results if r["confidently_wrong"]), len(results)),
        "over_refused": sum(1 for r in answerable if not r["correct"] and not r["answered"]),
        "answered_wrong": sum(1 for r in answerable if r["answered"] and not r["correct"]),
        "retrieval_hit_rate": _ratio(sum(1 for h in hits if h), len(hits)),
        "latency_p50_ms": round(pct(latencies, 0.50)),
        "latency_p95_ms": round(pct(latencies, 0.95)),
        "latency_mean_ms": round(statistics.fmean(latencies)) if latencies else 0.0,
        "failures": [r for r in results if not r["correct"]],
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def print_report(report: dict) -> None:
    print("\n" + "=" * 64)
    print("ProdEx evaluation report")
    print("=" * 64)
    rows = [
        (
            "Questions",
            f"{report['total']} "
            f"({report['answerable']} answerable, {report['refusable']} must-refuse)",
        ),
        ("Answer accuracy", f"{report['answer_accuracy']:.1%}"),
        ("Correct-refusal rate", f"{report['correct_refusal_rate']:.1%}"),
        ("Confident-wrong rate", f"{report['confident_wrong_rate']:.1%}"),
        ("  of which answered wrong", str(report["answered_wrong"])),
        ("  of which over-refused", str(report["over_refused"])),
        ("Retrieval hit rate", f"{report['retrieval_hit_rate']:.1%}"),
        ("Latency p50", f"{report['latency_p50_ms']} ms"),
        ("Latency p95", f"{report['latency_p95_ms']} ms"),
        ("Errors", str(report["errors"])),
    ]
    for label, value in rows:
        print(f"  {label:<24} {value}")

    if report["failures"]:
        print("\nFailures to investigate:")
        for failure in report["failures"]:
            expected = "should answer" if failure["should_answer"] else "should refuse"
            print(f"  - {failure['q'][:70]}  ({expected})")
            if failure.get("answer"):
                print(f"      {failure['answer'][:140]}")
            if failure["sources"]:
                print(f"      sources: {failure['sources'][:2]}")

    print("\nExit criteria (spec section 17):")
    print(f"  {'PASS' if report['answer_accuracy'] >= 0.85 else 'FAIL'}  answer accuracy >= 85%")
    print(f"  {'PASS' if report['confident_wrong_rate'] <= 0.05 else 'FAIL'}  confident-wrong <= 5%")
    print(f"  {'PASS' if report['correct_refusal_rate'] == 1.0 else 'FAIL'}  every must-refuse refused")
    print("=" * 64 + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ProdEx evaluation set")
    parser.add_argument("--questions", default=str(Path(__file__).parent / "questions.yaml"))
    parser.add_argument("--json", dest="json_out", default=None, help="also write the report as JSON")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    questions = load_questions(Path(args.questions))
    db.apply_schema()

    print(f"Corpus: {store.corpus_stats()}  docs version: {store.docs_version()}")
    if store.corpus_stats()["current"] == 0:
        print("\nThe index is empty. Run `make ingest` first.\n")
        return 2

    report = evaluate(questions, verbose=not args.quiet)
    print_report(report)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")

    return 0 if report["confident_wrong_rate"] <= 0.05 and report["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())