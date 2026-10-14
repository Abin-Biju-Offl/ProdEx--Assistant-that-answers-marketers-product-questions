# ProdEx

Internal **Product Knowledge Assistant** for non-technical marketers. It reads the product
documentation out of GitHub once, and then answers questions in Slack - with citations,
and with an honest "Not in the docs" instead of a guess.

This is Phase 1 of [`PHASE1_BUILD_SPEC.md`](PHASE1_BUILD_SPEC.md).

```
GitHub (read-only)  ->  ingestion: fetch -> gitleaks -> clean -> chunk -> embed
                                                     |
                                       Postgres + pgvector
                                                     |
                          FastAPI /ask  ->  hybrid search -> rerank -> threshold -> LLM
                                                     |
                                 Slack bot (Socket Mode)     Metabase (read-only logs)
```

## What it does

- **Never guesses.** Retrieval scores are checked against a threshold before the model is
  called, and the model's answer must contain a citation that points at a passage it was
  actually given. Otherwise the answer is "Not in the docs" plus who to ask.
- **Never leaks.** gitleaks runs over every document before it is indexed; a file with a
  secret in it is blocked and only its path is logged. Run as a non-root user, with an
  internal API key, and with a read-only database role for Metabase.
- **Never stale.** Every ingest bumps a `docs_version` that is part of the answer-cache
  key, so re-indexing invalidates every cached answer automatically.
- **Never untracked.** Every question, answer, source, score, latency and vote lands in
  Postgres, which is what the Metabase dashboard reads.

## Quick start

Requirements: Docker with Compose. Nothing else. Python 3.11 is needed only if you want to
run outside the container.

```bash
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health
```

Then index the sample content and try it:

```bash
make ingest                          # or: docker compose run --rm api python -m app.ingestion.pipeline
curl -X POST localhost:8000/ask \
  -H "X-Internal-Key: $(grep INTERNAL_API_KEY .env | cut -d= -f2)" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the API rate limit?","slack_user_id":"U123","channel_type":"dm"}'
```

Out of the box `GITHUB_SOURCE=mock`, so ingestion reads the sample product in
`fixtures/repo` and no GitHub credentials are needed. See
[Setting up GitHub](#setting-up-github) below.

## Commands

| Task | Command | Windows equivalent |
|---|---|---|
| Start everything | `make up` | `docker compose up -d` |
| Stop | `make down` | `docker compose down` |
| Re-index documents | `make ingest` | `docker compose run --rm api python -m app.ingestion.pipeline` |
| Run the tests | `make test` | `docker compose run --rm api pytest -q` |
| Run the evaluation | `make eval` | `docker compose run --rm api python eval/run_eval.py` |
| Lint | `make lint` | `docker compose run --rm api ruff check .` |
| Start the Slack bot | - | `docker compose --profile slack up -d slack` |
| Start the dashboard | - | `docker compose --profile dashboard up -d metabase` |
| Query the database | `make psql` | `docker compose exec db psql -U prodex -d prodex` |

## How it answers a question

1. Normalise the question and check the answer cache.
2. Filter to `status='current'` chunks the asker may see.
3. Hybrid search: vector (top 20) + Postgres full text (top 20), merged with Reciprocal
   Rank Fusion, then boosted for Product Truths, recent releases and fresh content.
4. Rerank the top 20 with a cross-encoder, keep 5.
5. **If the best rerank score is below `MIN_RERANK_SCORE`, the LLM is never called.**
6. Otherwise generate from those 5 passages only, with citations required.
7. Reject the answer if it has no valid `[n]` citation or is a refusal. Rejections become
   "Not in the docs".
8. Log everything to `requests`.

## Project layout

```
app/
  main.py            FastAPI: /ask /feedback /escalate /health /ingest
  config.py          every setting, env-driven
  db.py              connection pool and query helpers
  ingestion/         collect -> secret scan -> clean -> chunk -> embed
  chunking/          markdown, releases, issues, product truths
  retrieval/         embeddings, hybrid search + RRF, reranker, access filters
  generation/        LLM client, prompts, answer orchestration
  logging_/          request log, feedback, answer cache, retention
  slack/             Bolt Socket Mode bot, Block Kit, escalation notices
db/schema.sql        the whole schema, idempotent
eval/                questions.yaml + run_eval.py
fixtures/repo/       sample product used when GITHUB_SOURCE=mock
tests/               unit tests; no database or model required
docs/                DECISIONS, PRODUCT_TRUTHS, RUNBOOK
```

## Setting up GitHub

1. Create a GitHub App with **read-only** repository permissions
   (`Contents: read`, `Issues: read`, `Pull requests: read`, `Metadata: read`).
2. Install it on the **selected repositories only** - never "all repositories".
3. Download the private key to `secrets/github-app.pem` (git-ignored).
4. In `.env`:

   ```
   GITHUB_SOURCE=github
   GITHUB_APP_ID=Iv1.0123456789abcdef
   GITHUB_APP_INSTALLATION_ID=12345678
   GITHUB_PRIVATE_KEY_PATH=./secrets/github-app.pem
   GITHUB_REPOS=your-org/your-docs-repo,your-org/your-product-repo
   GITHUB_BRANCH=main
   INDEX_CODE=false
   ```

5. `make ingest`

`GITHUB_TOKEN` exists as a development-only fallback so you can try the pipeline before
the App exists. Never use it in production.

## Going live

1. Replace `eval/questions.yaml` with 30+ real marketer questions and the facts engineers
   say they should contain. The bundled set is synthetic.
2. Fill in `docs/PRODUCT_TRUTHS.md` in the source repo with engineer-approved facts. This
   content outranks everything else in retrieval.
3. Set a real `INTERNAL_API_KEY` and a real `METABASE_DB_PASSWORD`.
4. Create the Slack app with scopes `app_mentions:read`, `chat:write`, `commands`,
   `im:history`, `users:read`, enable Socket Mode, and set `SLACK_ALLOWED_CHANNELS`.
5. Work through the security checklist at the end of [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Status

All 13 steps of the spec are implemented and **verified running in Docker**: ingestion,
incremental re-ingest, `/ask` with citations, refusals, and **142 passing tests** including
the Postgres-backed API tests and the gitleaks test.

Two spec targets are **not met on this hardware**, and both are measured, not guessed:

| Target | Result |
|---|---|
| Answer accuracy >= 85% | 60.6% |
| Latency p95 < 5 s | 60 s |

Retrieval is not the constraint — the expected source was in the top 5 for **97%** of
questions. The gaps are the local LLM and the CPU. See D19 in
[`docs/DECISIONS.md`](docs/DECISIONS.md) for the measurements and the fix.

Also placeholder by design and needing real input: the GitHub credentials, the Slack app,
and 30+ real eval questions (the bundled 44 are synthetic, D15).