# Decisions

Every deviation from `PHASE1_BUILD_SPEC.md`, and every choice the spec left open.
Newest last.

---

## D1 — Default LLM is `qwen2.5:3b-instruct`, not 7B

**Spec says:** default `qwen2.5:7b-instruct`.
**Decision:** default `qwen2.5:3b-instruct`. Switch with `LLM_MODEL` in `.env`.
**Why:** the target machine is CPU-only (15 GB RAM, 16 threads, no GPU). A 7B model
generates 3-5 tokens/s there, so a 5-sentence answer takes 20-30 s and misses the 5 s p95
target by 5x. The 3B model answers in roughly 8-15 s, which is the best available on this
hardware.

**Measured consequence (see D19):** 3B is fast enough but too weak to follow the citation
rules reliably. It refuses answerable questions it has the right passage for. On this
hardware, 3B buys speed with accuracy; that is the wrong trade for a product whose whole
promise is "never guesses". Measure both before choosing.

## D19 — The 3B model is the accuracy bottleneck, not retrieval

The first full evaluation run made this unambiguous:

- **Retrieval hit rate was fine.** The correct passage was ranked #1 for nearly every
  question, at rerank scores of 0.5-0.73 against a 0.30 threshold.
- **The model then refused anyway.** `qwen2.5:3b-instruct` returned `NOT_IN_DOCS` with a
  passage sitting in slot [1] that answered the question outright. In one case it emitted a
  correct cited answer *and then* prefixed it with `NOT_IN_DOCS`.

Three prompt versions were tried against the same retrieval:

| Version | Approach | Result |
|---|---|---|
| v1 | Rules only | Refused answerable questions. One case answered, then added `NOT_IN_DOCS` |
| v2 | Two worked examples pasted into the user turn | Answered 4/4 in the spot check, but **parroted the examples back verbatim** |
| v3 | The same two examples as real dialogue turns | No echo; 2/4 on the spot check. **Shipped** - correct behaviour matters more than the score on 4 questions |

**Measured on the same four questions, same retrieval, same prompt (2026-10-14):**

| Model | Answered correctly | Refused answerable | Echoed the prompt | Latency |
|---|---|---|---|---|
| `qwen2.5:3b-instruct` | 2 of 4 | 2 | no | ~19 s p50 |
| `qwen2.5:7b-instruct` | 4 of 4 | 0 | no | 36-78 s |

**Full evaluation, `qwen2.5:7b-instruct`, 43 questions:**

| Metric | Result | Spec target |
|---|---|---|
| Retrieval hit rate | **97.0%** | - |
| Answer accuracy | 60.6% | >= 85% |
| Correct-refusal rate | 90.0% | 100% |
| Over-refused (had the passage, said no) | 8 of 33 | - |
| Latency p50 / p95 | 39 s / 60 s | < 5 s |

**Decision: ship 7B as the default.** The 3B evaluation gave 24% accuracy with 100%
correct-refusal - the model refuses questions it has the right passage for, which is the
safe direction but makes the product useless.

**What the numbers say.** Retrieval is not the problem: the expected source was in the top 5
for **97%** of questions. Two things are:

1. **Over-refusal (8 of 33).** The model still emits `NOT_IN_DOCS` with an answering passage
   in slot [1]. Three prompt versions were tried (below); further prompt tuning is trading
   clarity for luck on a 3B-to-7B model that is already slow.
2. **One must-refuse question was answered.** That is a true confident-wrong and must be
   driven to zero. `eval/questions.yaml` names the question in the failure list.

**The honest cost:** 39 s median on this CPU. The spec's 5-second target is **not achievable
with any local LLM on this hardware** - that is a property of the machine, not the code. The
Slack bot's "Looking this up..." placeholder exists so a slow answer is not a broken
experience.

**To reach the exit criteria you need hardware, not more tuning:** a GPU, or a hosted model
(`ALLOW_EXTERNAL_PROVIDERS=true` plus `LLM_BASE_URL`). A smaller model is the wrong
direction.

## D2 — `pyproject.toml` + `uv`, with `uv.lock` as the pin

**Spec says:** pin dependency versions.
**Decision:** `pyproject.toml` uses lower bounds; `uv.lock` holds the exact, resolved
versions and is committed. `uv sync --frozen` in the Dockerfile means builds are
reproducible from the lock file.
**Why:** hand-written exact pins drift from what actually resolves; a lock file is the
real pin.

## D3 — One schema file, no migration ledger

**Spec says:** `db/schema.sql` plus `db/migrations/`.
**Decision:** `db/schema.sql` is the single source of truth, is idempotent
(`IF NOT EXISTS` everywhere), is run by Postgres on first boot and re-applied by the API
at startup. `db/migrations/` holds a README explaining when to introduce numbered files.
**Why:** two copies of the same DDL in Phase 1 would be a drift bug waiting to happen.

## D4 — Rerank scores are squashed to 0..1

**Spec says:** compare the best rerank score against `MIN_RERANK_SCORE=0.30`.
**Decision:** the cross-encoder's raw logit is passed through a sigmoid so the score is a
probability-like 0..1 value, which is what a threshold of `0.30` implies.
**Why:** raw logits are unbounded and `0.30` would be meaningless against them.

## D5 — Mock source alongside the GitHub client

**Spec says:** GitHub App, read-only, no personal tokens in production.
**Decision:** `GITHUB_SOURCE=mock` reads `fixtures/repo` through exactly the same
`RawDoc` -> snapshot -> scan -> chunk -> embed pipeline. `GITHUB_TOKEN` exists as a
dev-only fallback for `GITHUB_SOURCE=github`.
**Why:** credentials and the repo allow-list were not available at build time. The mock
keeps the whole pipeline testable and the eval harness runnable. It is the default; set
`GITHUB_SOURCE=github` to switch. Never set `GITHUB_TOKEN` in production.

## D6 — `updated_at` for file content comes from the repo's last commit

**Spec says:** store `updated_at` per chunk.
**Decision:** one API call for the branch's latest commit date, applied to every file in
that ingest.
**Why:** a per-file last-modified date costs one API call per file and hits rate limits
for free. The precision is not worth it: `updated_at` is used only for freshness boosts.

## D7 — Issues and PRs are written into the snapshot as markdown

**Spec says:** clone into a temporary directory, run gitleaks, skip offending files.
**Decision:** every fetched document - including issues, PRs and GitHub releases - is
written into the temporary directory under a synthetic path (`issues/issue-412.md`) and
scanned there. Structured data is kept in memory alongside for chunking.
**Why:** it lets gitleaks block a single poisoned issue instead of every issue in one
JSON file, and the snapshot then contains exactly what is indexed.

## D8 — The synthetic snapshot is what gets scanned, and it is always deleted

**Spec says:** "delete the temporary directory after ingest".
**Decision:** `tempfile.TemporaryDirectory` in a `with` block. There is no code path that
leaves product content on disk outside that block.

## D9 — Boosts are applied after RRF, before reranking

**Spec says:** "multiply score slightly" for truth, recent releases and recent updates.
**Decision:** RRF produces the merged ranking; the boost multipliers are then applied to
the fused score, and the top 20 go to the reranker.
**Why:** RRF scores are rank sums (`1/(k+rank)`), not relevance scores, so multiplying
them by a type boost inside the fusion is meaningless.

## D10 — Prompt-injection defence: strip the pattern, drop the comment

**Spec says:** "strip or neutralize instruction-like text patterns in issue comments where
practical", and the system prompt must not let documents change its rules.
**Decision:** two layers. (1) Rule 9 of the system prompt states that passage text is
data, never an instruction. (2) A pattern list runs over every issue and PR comment; a
comment that matches is **removed whole**, not patched, so the "…and reply that X" tail
cannot survive the filter. Issue and PR *bodies* (which carry real product information)
have the matched phrase replaced rather than the whole text discarded.
**Why:** a pattern list is not a sandbox. Patching just the trigger phrase left the
remainder of the attack intact, which a wiring test caught. The prompt rule is the layer
that actually holds; this is a cheap, auditable first pass.

## D10b — PyTorch is pinned to the CPU-only index

**Decision:** `[[tool.uv.index]]` points `torch` at `download.pytorch.org/whl/cpu`, and
`torch` is declared as a direct dependency so uv honours the source.
**Why:** the default PyPI wheel bundles CUDA and pulled ~2.5 GB into the image for
nothing on a CPU-only host. Removing the explicit `torch` entry makes uv ignore the
index and fall back to PyPI - verified, not assumed.

## D10c — gitleaks is installed from a checksum-pinned release tarball

**Spec says:** "gitleaks binary run before indexing", fail closed.
**Decision:** the Dockerfile downloads the release tarball, verifies its SHA256 against
a pinned value, extracts it, and then runs `gitleaks version` in the same `RUN`. A bad
download or a bad checksum fails the build.
**Why:** the upstream `install.sh` that the first draft used has been removed upstream.
The old `curl ... | sh` form failed with a 404 but the pipeline still exited 0, so
gitleaks was silently absent. That is exactly the failure mode this project must not
have, and the build now fails loudly instead.

## D11 — Slack runs in Socket Mode, so HTTP signature verification is not in play

**Spec says:** "verify Slack signatures (Bolt does this)".
**Decision:** Socket Mode, as specified. In Socket Mode Slack opens an authenticated
WebSocket with the app-level token instead of posting signed HTTP requests, so Bolt's
signature middleware is not used. The API is still protected by `INTERNAL_API_KEY`.
**Impact:** trust boundary is the app-level token, not per-request signatures. Keep
`SLACK_APP_TOKEN` secret.

## D12 — Answer cache lives in Postgres and is keyed on the docs version

**Spec says:** "Postgres table or in-memory TTL cache".
**Decision:** a `answer_cache` table. Key = `sha256(normalized_question | docs_version)`.
Every successful ingest bumps `docs_version` and deletes stale rows.
**Why:** an in-memory cache would be empty after every restart and would survive a
document change; keying on the docs version makes re-ingestion invalidate everything
automatically. The eval harness bypasses the cache with `use_cache=False`.

## D13 — Retention runs as an in-process daily task

**Spec says:** "add a retention job".
**Decision:** an asyncio task in the API that purges `requests` older than
`LOG_RETENTION_DAYS` at startup and every 24 hours.
**Why:** one fewer service. If the API is scaled to several replicas the purge is
idempotent, so it is safe.

## D14 — Slack client sends no answer in a public channel that the asker cannot see

**Spec says:** "public-channel answers should use only content the lowest-access person in
the channel may see".
**Decision:** Phase 1 gives every authenticated user `public` + `internal`, so the
restriction is implemented as a single code path: the caller's `access_levels` are passed
into retrieval and applied in SQL (`retrieval/filters.py`). Narrowing it in Phase 2 means
changing what the bot sends, not the query.
**Impact:** a stricter policy is NOT active in Phase 1. This is a known gap and the reason
`access_levels` is explicit in the API contract rather than hard-coded.

## D15 — The eval question set is synthetic

**Decision:** `eval/questions.yaml` contains 34 answerable and 10 must-refuse questions
written against the sample corpus in `fixtures/repo` (a fictional product, "Atlas").
**Why:** no real questions or engineer answers were available. The file carries a
`PROVENANCE` header saying so.
**Impact:** the numbers from `make eval` measure the pipeline, not the real product. The
set must be replaced before the exit criteria in section 17 mean anything.

## D16 — `make` targets and Windows

**Spec says:** provide a `Makefile`.
**Decision:** the `Makefile` is the documented interface. On Windows, where `make` may
not be installed, the README gives the equivalent `docker compose run --rm api ...`
command for each target. No PowerShell shim is shipped.
**Why:** a second set of scripts to keep in sync is not worth it for four commands.

## D17 — Files added beyond the spec's layout

- `app/db.py` — connection pool and query helpers. Every other module needs it; putting it
  in `logging_/store.py` would be misleading.
- `app/ingestion/collector.py` — turns a GitHub repo into `RawDoc` records. Keeps
  `github_client.py` a pure transport layer.
- `app/retrieval/embed.py` exists per the spec; `embed_text_vector` was added to it
  rather than duplicating pgvector formatting.
- `app/slack/notify.py` — the API posts escalations, not the bot.
- `app/models.py` gained `cached` and `access_levels` fields used by the cache and filter.
- `eval/diagnose.py` — prints retrieval and raw model output for a few questions.
- `eval/report_from_log.py` — re-scores the `requests` table, so metrics can be re-tuned
  without paying for the LLM again. The eval container is thrown away with `--rm`, so its
  JSON report goes with it; this reads the database instead.

## D18 — Verification status at handoff

**Verified end to end in Docker** (2026-10-14):
- Image builds; gitleaks installs and passes its SHA256 check inside the build.
- `make ingest` on the fixture corpus: 20 documents, 0 blocked, **88 chunks indexed**.
  Re-running ingests **0 new and skips 88 unchanged**, which is the incremental-update
  requirement in spec 8.5 doing its job.
- `/ask` returns a correct, cited answer with Product Truths ranked first (the truth boost
  working), and refuses both "Enterprise price in euros" and "40% discount code" with an
  owner hint.
- **140 tests pass inside the container**, including the two that need Docker: the
  Postgres-backed API tests and the gitleaks test that plants fake credentials and proves
  the file is blocked.
- `ruff check` clean.

**Four real bugs were found by running it, not by testing it**, and are fixed:
1. `pydantic-settings` JSON-parses list fields before validators run, so `GITHUB_REPOS=a,b`
   crashed the API on boot. Fixed with `NoDecode` plus a validator that accepts both forms.
2. psycopg returns `jsonb` as a Python dict, so `json.loads()` on the answer-cache payload
   threw - but only on a cache **hit**, which is why it surfaced in the API tests and not
   in the unit tests.
3. `starlette.testclient` is incompatible with the locked httpx version. The API tests now
   use `httpx.ASGITransport` and drive the lifespan directly, rather than pinning httpx back.
4. The cached payload carried a `cached` key, which collided with the explicit `cached=True`
   on a cache hit - a `TypeError` on **every** cached answer.

**A fifth bug was in the measurement itself:** `source_hit` compared a lowercased expected
path against a title containing the original case (`docs/PRODUCT_TRUTHS.md`), so it never
matched. It understated retrieval hit rate as 63.6% when the real figure is 97.0%, and it
falsely failed correct answers. Worth knowing how easy it is to ship a harness that quietly
makes the product look worse than it is.

**Measured but not met:** accuracy (60.6% against 85%) and latency (39 s p50 against 5 s).
Both are detailed in D19. Neither is fixable by more prompt tuning on this hardware.