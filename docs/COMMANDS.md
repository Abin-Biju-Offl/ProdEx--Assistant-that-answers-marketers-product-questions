# ProdEx — Command Reference

Every command runs from the project root:

```powershell
cd "E:\WORK\Projects\ProdEx Agent\ProdEx"
```

You do **not** need `make` installed — this file uses the raw `docker compose`
commands, which work everywhere.

---

## 1. First-time setup (once)

```powershell
Copy-Item .env.example .env          # then edit: model, keys, repos
docker compose build api             # ~10 min, downloads PyTorch + gitleaks
docker compose pull                  # optional: pre-pull base images
```

Download the LLM once (about 5 GB):

```powershell
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

Put the GitHub App private key here (never committed — `secrets/` is gitignored):

```powershell
New-Item -ItemType Directory -Force secrets | Out-Null
Move-Item "$env:USERPROFILE\Downloads\*.pem" secrets\github-app.pem
```

---

## 2. Start and stop

```powershell
docker compose up -d                 # db + ollama + model-pull + api
docker compose ps                    # status
docker compose logs -f api           # follow API logs
docker compose logs -f db            # follow DB logs
docker compose down                  # stop, keep data
docker compose down -v               # stop and DELETE the database
```

Health check (should print `{"status":"ok","database":"ok",...}`):

```powershell
curl.exe -s http://localhost:8000/health
```

---

## 3. Ingest documents

**Check what will be indexed first** (free, no LLM, catches branch/permissions problems):

```powershell
docker compose run --rm api python eval/what_will_be_indexed.py
```

**Run the ingest:**

```powershell
docker compose run --rm api python -m app.ingestion.pipeline
```

Re-ingest after any doc change. Unchanged chunks are skipped automatically, so it is
cheap and safe to run often.

**Ingest one repo only:**

```powershell
docker compose run --rm api python -m app.ingestion.pipeline --repo Abin-Biju-Offl/Probagent-Plugin-Based-Tester-For-LLM-Agents
```

**Trigger via API instead** (returns immediately, runs in background):

```powershell
$key = ((Select-String INTERNAL_API_KEY .env).Line -split '=',2)[1]
curl.exe -X POST http://localhost:8000/ingest -H "X-Internal-Key: $key"
```

---

## 4. Tests, evaluation, lint

```powershell
# full suite (needs db up)
docker compose run --rm api uv run --frozen --group dev pytest -q

# one file
docker compose run --rm api uv run --frozen --group dev pytest tests/test_chunking.py -q

# lint
docker compose run --rm api uv run --frozen --group dev ruff check .

# full evaluation (~45 min with the 7B model on CPU)
docker compose run --rm api python eval/run_eval.py

# re-score the existing log without paying for the LLM again
docker compose run --rm api python eval/report_from_log.py

# see retrieval + raw model output for a few questions
docker compose run --rm api python eval/diagnose.py
```

---

## 5. Ask questions

Set the key once per PowerShell session:

```powershell
$key = ((Select-String INTERNAL_API_KEY .env).Line -split '=',2)[1]
```

**Ask:**

```powershell
$body = @{ question = "What is the API rate limit?"; slack_user_id = "U123"; channel_type = "dm" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri http://localhost:8000/ask -Method Post -Headers @{ "X-Internal-Key" = $key } -ContentType "application/json" -Body $body -TimeoutSec 900
```

**Answer cache** — ask the same question again and it returns instantly without calling
the model.

---

## 6. Feedback and escalation

```powershell
curl.exe -X POST http://localhost:8000/feedback -H "X-Internal-Key: $key" -H "Content-Type: application/json" -d '{\"request_id\":1,\"value\":1}'

curl.exe -X POST http://localhost:8000/escalate -H "X-Internal-Key: $key" -H "Content-Type: application/json" -d '{\"request_id\":1}'
```

`value` is `1` (helpful) or `-1` (not helpful).

---

## 7. Slack bot

Requires `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_ALLOWED_CHANNELS` in `.env`.

```powershell
docker compose --profile slack up -d slack
docker compose logs -f slack
docker compose --profile slack down
```

In Slack: DM the bot, `@mention` it in an allowed channel, or use `/askproduct <question>`.

---

## 8. Metabase dashboard

```powershell
docker compose --profile dashboard up -d metabase     # http://localhost:3000
docker compose --profile dashboard logs -f metabase
```

Connect as database `prodex`, host `db`, user `metabase_ro`, password `change_me`
(must match `db/schema.sql`). Paste queries from `metabase/queries.sql`.

---

## 9. Database

```powershell
# interactive
docker compose exec db psql -U prodex -d prodex

# one-off query
docker compose exec -T db psql -U prodex -d prodex -c "SELECT count(*) FROM chunks WHERE status='current';"

# what did we index?
docker compose exec -T db psql -U prodex -d prodex -c "SELECT repo, doc_type, count(*) FROM chunks WHERE status='current' GROUP BY 1,2 ORDER BY 1,2;"

# recent questions
docker compose exec -T db psql -U prodex -d prodex -c "SELECT id, answered, left(question,60), latency_ms FROM requests ORDER BY id DESC LIMIT 10;"

# ingest history
docker compose exec -T db psql -U prodex -d prodex -c "SELECT id, started_at, repo, files_seen, files_indexed, files_skipped_secrets, status FROM ingest_runs ORDER BY id DESC LIMIT 10;"

# shell into the API container
docker compose exec api bash
```

---

## 10. Backups

```powershell
docker compose exec -T db pg_dump -U prodex -d prodex | gzip > "prodex-$(Get-Date -Format yyyy-MM-dd).sql.gz"

# restore
gunzip -c backup.sql.gz | docker compose exec -T db psql -U prodex -d prodex
```

---

## 11. Troubleshooting

| Command | Purpose |
|---|---|
| `docker compose ps` | which containers are unhealthy |
| `docker compose logs --tail 50 api` | trace an API error |
| `docker compose restart api` | recover from a wedged process |
| `docker compose build --no-cache api` | rebuild after dependency changes |
| `docker system df` | check disk usage |
| `docker compose down -v && docker compose up -d` | full reset (destroys data) |

---

## Daily loop

```powershell
docker compose up -d                                                    # start
docker compose run --rm api python -m app.ingestion.pipeline          # after doc changes
docker compose run --rm api python eval/run_eval.py                   # before calling it a day
docker compose down                                                    # stop
```