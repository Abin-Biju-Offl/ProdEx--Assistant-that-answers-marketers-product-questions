# Runbook

Day-to-day operations for ProdEx. Everything here assumes you are in the project root
with Docker.

## Start and stop

```bash
cp .env.example .env        # first time only
docker compose up -d        # db, ollama, model pull, api
curl http://localhost:8000/health
```

The first start pulls `qwen2.5:3b-instruct` (about 2 GB) and the embedding and reranker
models (about 1.3 GB). Allow 10-20 minutes on a cold machine.

```bash
docker compose down         # stop
docker compose down -v      # stop and delete the database and model cache
```

## Everyday commands

| Task | Command |
|---|---|
| Re-index after a docs change | `make ingest` |
| Run the tests | `make test` |
| Run the evaluation | `make eval` |
| Lint | `make lint` |
| Look at the request log | `make psql` |
| Tail the API log | `make logs` |

Without `make` on Windows, use `docker compose run --rm api <command>` with the same
arguments (see D16 in DECISIONS.md).

---

## Ingestion

`POST /ingest` or `make ingest` re-indexes the allow-listed repos.

- Unchanged files are skipped: a chunk whose `content_hash` is unchanged is not re-embedded.
- Deleted or rewritten chunks are marked `status='deprecated'`, never deleted.
- Every run is recorded in `ingest_runs` with file counts and blocked files.

```bash
# recent runs
docker compose exec db psql -U prodex -d prodex -c \
  "SELECT id, started_at, repo, files_seen, files_indexed, files_skipped_secrets, status
   FROM ingest_runs ORDER BY id DESC LIMIT 10;"

# anything currently deprecated
docker compose exec db psql -U prodex -d prodex -c \
  "SELECT repo, path, count(*) FROM chunks WHERE status='deprecated' GROUP BY 1,2 LIMIT 20;"
```

### A file was blocked by the secret scan

`ingest_runs.files_skipped_secrets` counts it. Find which files:

```bash
docker compose run --rm api python -m app.ingestion.pipeline --log-level INFO 2>&1 | grep "secret scan"
```

The scan logs the **path** and the rule name only. Never the secret. If a file is blocked
but contains no real secret, add an inline `# gitleaks:allow` comment on the offending
line **in the source repo** and re-ingest. Do not remove the file from the scan.

### Ingestion failed

`ingest_runs.status='failed'` with the reason in `ingest_runs.error`. A
`SecretScanError` means nothing was indexed - that is deliberate (fail closed). Fix the
cause and re-run; do not work around it.

---

## Evaluation

Run `make eval` after every change to chunking, prompts, thresholds or models.

The report is the release gate:

| Metric | Target |
|---|---|
| Answer accuracy | >= 85% |
| Confident-wrong rate | <= 5%, ideally 0 |
| Correct-refusal rate | 100% |
| Latency p95 | < 5000 ms |

**Investigate every confident-wrong answer before shipping.** Each failure line prints the
question, what was said and which sources were cited. The usual causes, in order:

1. The fact is not in the corpus -> add it to `docs/PRODUCT_TRUTHS.md` in the source repo.
2. The right chunk was retrieved but did not make the top 5 -> adjust `CHUNK_MAX_TOKENS`.
3. The right chunk was in the top 5 but the model ignored it -> adjust the prompt and bump
   `PROMPT_VERSION`.
4. The reranker scored the right chunk too low -> adjust `MIN_RERANK_SCORE`.

Re-baseline the numbers before and after any change so you know what the change bought.

---

## Slack bot

```bash
docker compose --profile slack up -d slack
docker compose logs -f slack
```

Triggers:

| Trigger | Behaviour |
|---|---|
| DM to the bot | Answers in the DM. |
| `@mention` in an allowed channel | Acknowledges instantly, replies in a thread. |
| `/askproduct <question>` | Same, but in the command's channel. |

The bot answers in about 3 seconds with "Looking this up…", then edits that message with
the answer. Buttons: 👍 Helpful, 👎 Not helpful, Escalate to engineering.

**Nothing appears in Slack?** Check in order: `SLACK_ALLOWED_CHANNELS` contains the
channel ID; both tokens start with `xoxb-` / `xapp-`; the bot has been invited to the
channel (`/invite @prodex`).

**Duplicate answers?** De-duplication holds recent event IDs for 5 minutes. If duplicates
persist, the API key is wrong and the first call is being rejected rather than de-duplicated -
check `docker compose logs api`.

---

## Dashboard

```bash
docker compose --profile dashboard up -d metabase   # http://localhost:3000
```

Metabase connects as the read-only `metabase_ro` user and can see `requests` and
`ingest_runs`. It cannot see document content (`chunks` is not granted).

On first run: create an account, then add a database with the settings shown in the setup
screen, then paste the SQL from `metabase/queries.sql` into a Native query to create each
chart. Ready-made questions and dashboard layout are described in that file.

If Metabase cannot connect, `METABASE_DB_PASSWORD` in `.env` must match the password in
`db/schema.sql`. Both default to `change_me`; change both together.

---

## Housekeeping

### Retention

`requests` rows older than `LOG_RETENTION_DAYS` (default 180) are deleted daily by an
in-process task. Slack user IDs only are stored - never names, never emails.

### Answer cache

Cleared automatically whenever an ingest succeeds, because the key includes the docs
version. If answers look stale, check that ingest has actually run:

```bash
curl http://localhost:8000/health | python -m json.tool
```

### Backups

```bash
docker compose exec db pg_dump -U prodex -d prodex | gzip > prodex-$(date +%F).sql.gz
```

Restore with `gunzip -c backup.sql.gz | docker compose exec -T db psql -U prodex -d prodex`.

---

## Security checklist (spec section 14)

Run through this before inviting anyone to use the bot.

| # | Requirement | How to verify |
|---|---|---|
| 1 | GitHub App is read-only and installed on selected repos only | GitHub > Settings > Installed Apps: permissions = "Metadata, read-only"; installation = "Selected repositories only" |
| 2 | No secrets in the repo | `git log --all -p \| grep -i "secret_key\|api_key="` returns nothing; `.env` and `*.pem` are git-ignored |
| 3 | gitleaks runs before indexing | `make ingest` log shows "secret scan blocked N of M files"; plant a fake key and confirm its file is skipped |
| 4 | No secrets or restricted content in stdout | `docker compose logs api \| grep -i "token\|password"` returns nothing but request ids |
| 5 | Slack IDs only, no names or emails | `SELECT DISTINCT slack_user_id FROM requests;` shows U-ids only |
| 6 | API is key-protected, Slack is authenticated | `curl -X POST localhost:8000/ask` without a key returns 401 |
| 7 | Metabase uses a read-only role | `SELECT has_table_privilege('metabase_ro','chunks','SELECT');` returns false |
| 8 | No content leaves the machine | `ALLOW_EXTERNAL_PROVIDERS=false`; `docker compose logs api \| grep -i "openai\|anthropic"` returns nothing |
| 9 | Retrieved text is treated as data | System prompt rule 9; `neutralize_instructions` applied to issue text; the fixture corpus contains an injection attempt in issue 412 |
| 10 | Containers non-root, versions pinned, ports minimal | `docker compose exec api whoami` returns a non-root user; `uv.lock` is committed; only 8000, 11434, 3000 are published |

---

## Recovering from a bad answer

1. Find the request: `SELECT * FROM requests WHERE id = <id>;`
2. Check which chunks were cited: `SELECT * FROM chunks WHERE id = ANY(chunk_ids);`
3. If the corpus is wrong, fix the source repo, re-ingest, and the answer cache clears itself.
4. If the model is wrong on correct context, add the fact to `docs/PRODUCT_TRUTHS.md` in the
   source repo - that beats prompt tuning almost every time.