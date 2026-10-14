"""Diagnostic: why are answerable questions being refused? Not part of the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.generation.llm import get_llm  # noqa: E402
from app.generation.prompts import NOT_IN_DOCS, build_messages  # noqa: E402
from app.retrieval.filters import normalize_levels  # noqa: E402
from app.retrieval.search import hybrid_search, rerank  # noqa: E402

QUESTIONS = [
    "Which export formats do we support?",
    "Can we sell SCIM provisioning?",
    "How long do you keep customer data?",
    "What is the API rate limit?",
]

levels = normalize_levels(["public", "internal"])
llm = get_llm()

for q in QUESTIONS:
    cands = hybrid_search(q, levels, 20)
    top = rerank(q, cands, 5)
    print("=" * 70)
    print("Q:", q)
    print("  top rerank score:", round(top[0]["rerank_score"], 4) if top else None)
    for i, c in enumerate(top, 1):
        print(f"   [{i}] {c['rerank_score']:.3f}  {c['path']} > {c['heading_path'][:40]}")
    raw = llm.chat(build_messages(q, top))
    print("  RAW MODEL OUTPUT:")
    print("   ", repr(raw[:400]))
    print("  starts with NOT_IN_DOCS:", raw.strip().upper().startswith(NOT_IN_DOCS))