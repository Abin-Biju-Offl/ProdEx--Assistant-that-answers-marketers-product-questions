# Product Knowledge Assistant: Phase 1 Build Spec

**Audience:** the coding agent (OpenCode, MiniMax "Space Bunny" model) that will build this from scratch.
**Goal of this file:** give you the full context, from problem to solution, so you can build Phase 1 end to end without asking for clarification. Where a decision is not specified, pick the simplest option that satisfies the security and accuracy rules, and record it in `docs/DECISIONS.md`.

---

## 1. Problem Statement

Our marketers are non-technical. They need to understand the product well enough to write accurate messaging, answer customers, and brief sales. Today they:

- Cannot read the code or the technical docs in GitHub.
- Ask engineers the same questions repeatedly, which is slow and interrupts engineering.
- Risk promising features that do not exist, or stating limits incorrectly.
- Have no record of what they were told, so the same gaps keep reappearing.

Customers also ask "why is it not working?" and marketers need to route those questions well without guessing.

### The pain, in one line
Marketers cannot get **correct, sourced, plain-language** answers about the product on demand, and nobody tracks what they ask.

---

## 2. Solution Summary

Build an internal **Product Knowledge Assistant** (RAG: retrieval-augmented generation) that:

1. Securely pulls product context from selected GitHub repos (read-only).
2. Indexes it into Postgres + pgvector.
3. Answers marketer questions in **Slack**, using only retrieved context, with citations.
4. Says "Not in the docs" and names an owner when it is not confident, instead of guessing.
5. Logs every request, answer, source, score, and feedback in Postgres.
6. Shows the log in a Metabase dashboard.

**Phase 1 = this whole document.** Anything not listed here is out of scope.

---

## 3. Goals and Non-Goals

### Goals (Phase 1)
- Accurate answers with citations; near-zero confident wrong answers.
- Simple, secure, reasonably fast (target 2-5 seconds per answer).
- Runs locally with one command (`docker compose up`).
- Free to run: open-weight LLM and open-source components by default.
- Every component swappable through configuration (LLM, embeddings, reranker).

### Non-Goals (do NOT build)
- Agents with many tools, knowledge graphs, fine-tuning.
- Role-based access beyond a simple `public` / `internal` tag (Phase 2).
- CRM integration, marketing-copy generation, ticket creation (Phase 2).
- A custom web front end (Slack is the interface; Metabase is the dashboard).

---

## 4. Users and Key Scenarios

| User | Scenario | Expected result |
|---|---|---|
| Marketer | "Does the product support SSO?" | Short answer + source links, or "Not in the docs, ask @owner" |
| Marketer | "What changed in the last release?" | Summary from release notes with links |
| Marketer | "A customer says export is failing. What do I do?" | Known limits/issues from docs + the facts to collect + escalate button |
| Product owner | "What are marketers asking that we haven't documented?" | Metabase view of unanswered and low-rated questions |

---

## 5. Architecture

```
GitHub (read-only App)
        |
   [Ingestion job]  -> secret scan -> clean -> chunk -> embed
        |
   Postgres + pgvector  (chunks, vectors, metadata, request logs)
        ^
        |
   [FastAPI /ask]  <-- hybrid search -> rerank -> threshold check -> LLM (strict prompt)
        ^
        |
   [Slack Bolt bot]  (Socket Mode)          Metabase --> reads logs (read-only DB user)
```

### Components
1. **Ingestion**: pulls and indexes content, runs on demand and on a schedule or webhook.
2. **API (FastAPI)**: `/ask`, `/feedback`, `/health`, `/ingest` (admin only).
3. **Slack bot (Bolt for Python)**: thin layer; passes question + Slack user ID to the API and formats the reply.
4. **Postgres + pgvector**: single datastore for chunks, embeddings, and logs.
5. **Metabase**: dashboards on the log tables.
6. **Model servers**: Ollama (LLM) and local embedding/reranker models, all behind config.

---

## 6. Tech Stack (use exactly this unless blocked)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| API | FastAPI + Uvicorn | |
| DB | Postgres 16 + `pgvector` | One DB for vectors and logs |
| DB access | `psycopg[binary]` 3 + `pgvector` python package | Keep SQL explicit; no heavy ORM |
| GitHub | GitHub App (read-only), `PyGithub` or plain `httpx` against REST API | Short-lived installation tokens |
| Secret scan | `gitleaks` binary run before indexing | Fail closed on findings |
| Chunking | Own code in `app/chunking/` | Markdown-aware, see section 8 |
| Tokens | `tiktoken` (or HF tokenizer) | For size limits |
| Embeddings | Default: `BAAI/bge-small-en-v1.5` via `sentence-transformers` (free, local) | Configurable to OpenAI/Voyage |
| Keyword search | Postgres full-text (`tsvector` + GIN) | |
| Hybrid merge | Reciprocal Rank Fusion (RRF), own code | |
| Reranker | Default: `BAAI/bge-reranker-base` (local) | Configurable to Cohere/Voyage |
| LLM | Default: Ollama running `qwen2.5:7b-instruct` (or Llama 3.1 8B) | Called through an OpenAI-compatible client so it can be swapped to vLLM or a paid API |
| Slack | `slack-bolt` (Socket Mode) | |
| Cache | Postgres table or in-memory TTL cache | Add Redis only if needed |
| Dashboard | Metabase (Docker) | Read-only DB user |
| Packaging | Docker + docker-compose | |
| Tests | `pytest`, plus the eval script in section 12 | |
| Lint | `ruff` | |

Do **not** add LangChain or LlamaIndex. Build the small pipeline yourself so every step is visible and testable. Standard libraries for primitives (HTTP, DB, tokenizers, model loading) are fine.

---

## 7. Repository Layout (create this)

```
product-assistant/
  README.md
  PHASE1_BUILD_SPEC.md          # this file
  docker-compose.yml
  .env.example
  .gitignore                    # must exclude .env, *.pem, data/
  Makefile                      # make up | ingest | eval | test
  docs/
    DECISIONS.md
    PRODUCT_TRUTHS.md           # hand-written, engineer-approved facts
    RUNBOOK.md
  db/
    schema.sql
    migrations/
  app/
    main.py                     # FastAPI app
    config.py                   # env-driven settings (pydantic-settings)
    models.py                   # request/response schemas
    ingestion/
      github_client.py          # App auth, fetch files/issues/PRs/releases
      secret_scan.py            # gitleaks wrapper
      cleaners.py               # drop bots, +1s, lockfiles, generated files
      pipeline.py               # orchestrates ingest end to end
    chunking/
      markdown.py               # heading-based splitter
      issues.py                 # issue/PR chunker
      releases.py               # changelog/release chunker
      truths.py                 # Product Truths Q&A chunker
      common.py                 # token counting, context prefix
    retrieval/
      embed.py                  # embedding provider interface
      search.py                 # vector + keyword + RRF
      rerank.py                 # reranker interface
      filters.py                # access level, status filters
    generation/
      llm.py                    # OpenAI-compatible client wrapper
      prompts.py                # system prompt + templates
      answer.py                 # orchestrates retrieve -> threshold -> LLM
    logging_/
      store.py                  # request log + feedback
    slack/
      bot.py                    # Bolt app, events, commands, buttons
      blocks.py                 # Block Kit builders
  eval/
    questions.yaml              # 30+ questions with expected facts + sources
    run_eval.py
  tests/
```

---

## 8. Ingestion and Chunking

### 8.1 What to pull (only from allow-listed repos, `main` branch)
- `README*`, `/docs/**`, `*.md` documentation
- Release notes, `CHANGELOG*`, GitHub Releases
- Closed issues and merged PR descriptions (title, body, final resolution, key comments)
- Labels such as `bug`, `limitation`, `wontfix`, `breaking-change`
- ADRs / architecture notes if present
- `docs/PRODUCT_TRUTHS.md` (highest priority)
- Code only if explicitly enabled by config (default **off**)

### 8.2 What to exclude
`.env*`, config files with credentials, private keys, lockfiles, build output, vendored/generated files, binary files, bot comments, "+1" replies.

### 8.3 Secret scanning (mandatory)
1. Clone or fetch content into a temporary directory.
2. Run `gitleaks detect --no-git` on it.
3. If any finding exists, **do not index the offending file**; log the path (never the secret) and continue.
4. Delete the temporary directory after ingest.

### 8.4 Chunking rules

| Content | Strategy | Size |
|---|---|---|
| Markdown docs | Split on H2/H3; keep heading path | 300-600 tokens |
| Release notes | One chunk per release or per feature entry | 200-400 tokens |
| Issues / PRs | Title + description + resolution + key comments (summarize long threads) | 300-500 tokens |
| ADRs | One chunk per decision (context, decision, consequences) | 400-600 tokens |
| Product Truths | One chunk per fact or Q&A pair | 100-200 tokens |
| Code (optional) | Function/class with docstring | 200-400 tokens |

Rules:
- Never split inside a table, list, or code block.
- Overlap 10-15% **only** when a section exceeds the max size and must be split by length.
- Prepend a context line to every chunk's embedding text: `Repo > File > Heading path`.
- Store metadata on every chunk: `repo`, `path`, `url`, `doc_type`, `version`, `updated_at`, `access_level` (`public`/`internal`), `status` (`current`/`deprecated`), `content_hash`.
- Mark outdated content `deprecated` rather than deleting it.
- For issues with long threads (>10 comments): store a short LLM-generated summary plus the resolution comment. Keep the summarization prompt in `prompts.py`.

### 8.5 Incremental updates
- Use `content_hash` to skip unchanged chunks.
- On re-ingest, upsert changed chunks and mark removed files' chunks `deprecated`.
- Provide `make ingest` (full) and an admin endpoint `POST /ingest?repo=...` (protected by an API key).
- Webhook support can be added after the core flow works.

---

## 9. Database Schema (start here; refine as needed)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
  id            BIGSERIAL PRIMARY KEY,
  repo          TEXT NOT NULL,
  path          TEXT NOT NULL,
  url           TEXT NOT NULL,
  doc_type      TEXT NOT NULL,          -- readme|doc|release|issue|pr|adr|truth|code
  heading_path  TEXT,
  content       TEXT NOT NULL,          -- text shown to the LLM
  embed_text    TEXT NOT NULL,          -- context-prefixed text that was embedded
  embedding     VECTOR(384),            -- match the embedding model dimension
  tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', embed_text)) STORED,
  version       TEXT,
  access_level  TEXT NOT NULL DEFAULT 'internal',
  status        TEXT NOT NULL DEFAULT 'current',
  content_hash  TEXT NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL,
  indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (repo, path, heading_path, content_hash)
);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX chunks_status_idx ON chunks (status, access_level);

CREATE TABLE requests (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  slack_user_id   TEXT NOT NULL,        -- ID only, no names or emails
  channel_type    TEXT,                 -- dm|channel
  question        TEXT NOT NULL,
  answer          TEXT,
  answered        BOOLEAN NOT NULL,     -- false when "not in the docs"
  top_score       REAL,
  chunk_ids       BIGINT[],
  latency_ms      INTEGER,
  model           TEXT,
  escalated       BOOLEAN NOT NULL DEFAULT false,
  feedback        SMALLINT,             -- 1 helpful, -1 not helpful
  feedback_note   TEXT
);

CREATE TABLE ingest_runs (
  id          BIGSERIAL PRIMARY KEY,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  repo        TEXT,
  files_seen  INT, files_indexed INT, files_skipped_secrets INT,
  status      TEXT
);

-- Read-only role for Metabase
CREATE ROLE metabase_ro LOGIN PASSWORD 'change_me';
GRANT SELECT ON requests, ingest_runs TO metabase_ro;   -- not chunks content by default
```

Add a retention job (config: `LOG_RETENTION_DAYS`, default 180) that deletes old `requests` rows.

---

## 10. Retrieval and Answering Pipeline

For each question:

1. **Normalize** the question (trim, collapse whitespace). Check the answer cache (key = normalized question + `docs_version`).
2. **Filter**: only `status='current'` and `access_level` allowed for this user. In Phase 1 every authenticated user gets `public` + `internal`, but the filter must exist in code.
3. **Hybrid search**:
   - Vector: top 20 by cosine similarity on the question embedding.
   - Keyword: top 20 by `ts_rank` on `plainto_tsquery`.
   - Merge with RRF (`k=60`), keep top 20.
4. **Boosts**: multiply score slightly for `doc_type='truth'` (highest), recent release notes, and recent `updated_at`.
5. **Rerank** the 20 with the cross-encoder; keep top 5.
6. **Threshold check**: if the best rerank score is below `MIN_RERANK_SCORE` (config, tune with the eval set), do NOT call the LLM. Return the "not in the docs" response.
7. **Generate**: call the LLM with the system prompt (section 11) and the top 5 chunks, each labeled `[1]`, `[2]`, ... with source URL.
8. **Validate**: ensure the answer contains at least one citation marker that maps to a provided chunk. If not, treat it as "not in the docs".
9. **Log** everything to `requests` and return the response.

### API contract

`POST /ask`
```json
{ "question": "string", "slack_user_id": "U123", "channel_type": "dm" }
```
Response:
```json
{
  "request_id": 42,
  "answered": true,
  "answer": "short plain-language answer with [1] [2] markers",
  "sources": [{"n": 1, "title": "docs/limits.md > Rate limits", "url": "https://github.com/...", "updated_at": "2026-09-30"}],
  "confidence": 0.82,
  "docs_as_of": "2026-10-12",
  "owner_hint": "Ask @product-owner"
}
```

`POST /feedback` `{ "request_id": 42, "value": 1|-1, "note": "optional" }`
`POST /escalate` `{ "request_id": 42 }` (records the flag and notifies a configured Slack channel)
`GET /health`

All endpoints except `/health` require an internal API key (header) so only the Slack bot and admins can call them.

---

## 11. System Prompt (put in `prompts.py`, keep versioned)

```
You are an internal product assistant for marketers who are not technical.

Rules:
1. Answer ONLY using the numbered context passages provided. Never use outside knowledge.
2. Cite every claim with its passage number, like [1] or [2].
3. If the passages do not clearly answer the question, reply exactly: "NOT_IN_DOCS".
4. Never promise or imply a feature exists unless a passage states it. If a passage describes
   something planned or on a roadmap, say "planned, not committed".
5. If passages conflict, prefer the newer one and mention the conflict briefly.
6. Write in plain language, 2-5 sentences, no jargon. If you must use a technical term, explain it in a few words.
7. Do not give legal, pricing-commitment, or security-compliance claims unless a passage states them explicitly.
8. If the user describes a customer problem, list (a) what the docs say about known limits or causes,
   and (b) which facts to collect before escalating (what they tried, error message, device/version, when it started).
```

When the model returns `NOT_IN_DOCS`, the API returns `answered=false` with the standard message and owner hint.

---

## 12. Evaluation (build this early, not last)

Create `eval/questions.yaml` with at least **30** real questions, each with:
```yaml
- q: "What is the API rate limit?"
  must_include: ["100 requests"]
  expected_source: "docs/limits.md"
  should_answer: true
- q: "Does it support on-premise install?"
  should_answer: false      # not in docs, must say NOT_IN_DOCS
```
`run_eval.py` reports:
- Answer accuracy (must_include satisfied and cited)
- Correct-refusal rate (should_answer=false cases handled)
- **Confident-wrong rate** (answered but wrong): the most important metric
- p50 / p95 latency
- Average retrieval hit rate (expected source in top 5)

Seed the first 30 questions from the repos' real docs and past engineer-answered questions. Re-run after every change to chunking, prompts, thresholds, or models.

---

## 13. Slack Bot Requirements

- Use **Bolt for Python in Socket Mode** (no public URL needed).
- Triggers: DM to the bot, `@mention` in allowed channels, and `/askproduct <question>`.
- **3-second rule:** acknowledge immediately, post a "Looking this up…" message, then update that message with the final answer. Run the API call in the background.
- Reply in a thread when invoked in a channel.
- Deduplicate retried events by event ID (store recent IDs for a few minutes).
- Answer message (Block Kit) contains:
  - Short answer text
  - Source links in a small context block, plus "Docs as of <date>"
  - Buttons: 👍 Helpful, 👎 Not helpful, **Escalate to engineering**
  - If not answered: "Not in the docs. Ask <owner>" plus the Escalate button
- Button clicks call `/feedback` and `/escalate`, then update the message to confirm.
- Slack scopes (minimum): `app_mentions:read`, `chat:write`, `commands`, `im:history`, `users:read`.
- Restrict to configured channel IDs. Public-channel answers should use only content the lowest-access person in the channel may see; sensitive questions are answered in DMs only.

---

## 14. Security Requirements (non-negotiable)

1. GitHub App, **read-only**, installed on selected repos only. No personal tokens in production.
2. Secrets only in environment variables or a secrets manager; `.env` is git-ignored; ship `.env.example` only.
3. Gitleaks scan before indexing; findings block the file.
4. Never log secrets, tokens, or full prompts containing restricted content to stdout. Log request IDs.
5. Log Slack user IDs only (no names or emails); retention job enforced.
6. Verify Slack signatures (Bolt does this); API protected by an internal key.
7. Metabase connects with a read-only DB user.
8. No outbound calls with private content to third-party LLM or embedding services unless explicitly enabled in config (`ALLOW_EXTERNAL_PROVIDERS=false` by default).
9. Treat retrieved text as **untrusted data**: the system prompt must not let document content change the assistant's rules (basic prompt-injection defense). Strip or neutralize instruction-like text patterns in issue comments where practical.
10. Containers run as non-root; pin dependency versions; no unnecessary ports exposed.

---

## 15. Configuration (`.env.example`)

```
# GitHub
GITHUB_APP_ID=
GITHUB_APP_INSTALLATION_ID=
GITHUB_APP_PRIVATE_KEY_PATH=./secrets/github-app.pem
GITHUB_REPOS=org/repo1,org/repo2
GITHUB_BRANCH=main
INDEX_CODE=false

# Database
DATABASE_URL=postgresql://app:app@db:5432/assistant

# Models
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=qwen2.5:7b-instruct
LLM_API_KEY=ollama
EMBED_PROVIDER=local
EMBED_MODEL=BAAI/bge-small-en-v1.5
RERANK_PROVIDER=local
RERANK_MODEL=BAAI/bge-reranker-base
ALLOW_EXTERNAL_PROVIDERS=false

# Retrieval
TOP_K_RETRIEVE=20
TOP_K_FINAL=5
MIN_RERANK_SCORE=0.30

# Slack
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
SLACK_ALLOWED_CHANNELS=
ESCALATION_CHANNEL=
OWNER_HINT="the product owner"

# API / ops
INTERNAL_API_KEY=
LOG_RETENTION_DAYS=180
```

---

## 16. Build Order (follow in sequence; verify each step before the next)

| # | Step | Done when |
|---|---|---|
| 1 | Scaffold repo, docker-compose (db, api, ollama, metabase), config, health check | `docker compose up` works; `/health` returns 200 |
| 2 | DB schema + migrations | Tables and indexes exist; pgvector works |
| 3 | GitHub client + secret scan + cleaners | Allow-listed repos fetched; a planted fake secret blocks its file |
| 4 | Chunkers + unit tests | Tests prove no mid-table/code-block splits and correct metadata |
| 5 | Embeddings + indexing pipeline + `make ingest` | Chunks and vectors in DB; re-run skips unchanged content |
| 6 | Hybrid search + RRF + reranker | Retrieval hit rate measured on eval set |
| 7 | LLM wrapper + prompt + threshold + citation validation + `/ask` | Correct cited answers; "NOT_IN_DOCS" path works |
| 8 | Request logging + `/feedback` + `/escalate` | Rows written for every request |
| 9 | Eval harness + 30 questions | Report prints all metrics from section 12 |
| 10 | Tune chunking, thresholds, prompt against eval | Meets exit criteria |
| 11 | Slack bot (acks, placeholder update, buttons, dedupe) | Works in DM and an allowed channel |
| 12 | Metabase dashboard | Top questions, unanswered, feedback trend, latency, ingest runs |
| 13 | Hardening: retention job, non-root containers, security checklist, README + RUNBOOK | Section 14 checklist all ticked |

Write tests as you go. Commit after each step with a clear message.

---

## 17. Phase 1 Exit Criteria

- At least 85-90% of the eval questions answered correctly **and** cited.
- Confident-wrong answers close to zero (investigate every one).
- All "should not answer" questions return "Not in the docs".
- p95 answer time under about 5 seconds on the target hardware.
- No secrets or restricted content in the index (verified by scan and spot check).
- 3-5 marketers use it for 2 weeks; the log is reviewed weekly and gaps fed back into docs / Product Truths.
- Security checklist (section 14) fully satisfied.

---

## 18. Rules for You, the Coding Agent

1. **Build from scratch, in the order of section 16.** Do not skip the eval harness.
2. **Keep it simple.** No extra frameworks, no speculative features. Choose the plain solution.
3. **Never invent product facts.** The assistant's content comes only from the indexed repos. Do not hard-code product claims.
4. **Fail closed.** If a scan, auth check, or threshold fails, refuse rather than proceed.
5. **Everything configurable, nothing secret in code.**
6. **Explain decisions.** Add short entries to `docs/DECISIONS.md` for any deviation from this spec.
7. **Ask for human input only when blocked** on something only the owner can provide: GitHub App credentials, Slack tokens, repo allow-list, owner name, and the first set of real questions for the eval set. List all such blockers up front in your first message.
8. **When finished,** summarize what was built, how to run it, eval results, and known gaps in under 200 words.

---

## 19. Phase 2 (for context only, do not build)

Role-based access, Slack/CRM workflows, auto-drafting marketing copy with claim checking, escalation tickets, richer dashboards, webhook-driven re-indexing.
