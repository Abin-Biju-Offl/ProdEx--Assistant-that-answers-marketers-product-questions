-- ---------------------------------------------------------------------------
-- ProdEx Phase 1 schema. Single source of truth.
-- Applied by Postgres on first boot (docker-entrypoint-initdb.d) and re-applied
-- idempotently by the API on every start. See docs/DECISIONS.md.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

-- --- Knowledge base -------------------------------------------------------

CREATE TABLE IF NOT EXISTS chunks (
  id            BIGSERIAL PRIMARY KEY,
  repo          TEXT NOT NULL,
  path          TEXT NOT NULL,
  url           TEXT NOT NULL,
  doc_type      TEXT NOT NULL,          -- readme|doc|release|issue|pr|adr|truth|code
  heading_path  TEXT NOT NULL DEFAULT '',
  content       TEXT NOT NULL,          -- text shown to the LLM
  embed_text    TEXT NOT NULL,          -- context-prefixed text that was embedded
  embedding     VECTOR(384),            -- must match EMBED_MODEL output dimension
  tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', embed_text)) STORED,
  version       TEXT,
  access_level  TEXT NOT NULL DEFAULT 'internal',   -- public|internal
  status        TEXT NOT NULL DEFAULT 'current',     -- current|deprecated
  content_hash  TEXT NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL,
  indexed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (repo, path, heading_path, content_hash),
  CONSTRAINT chunks_doc_type_chk CHECK (doc_type IN
    ('readme','doc','release','issue','pr','adr','truth','code')),
  CONSTRAINT chunks_access_level_chk CHECK (access_level IN ('public','internal')),
  CONSTRAINT chunks_status_chk CHECK (status IN ('current','deprecated'))
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx       ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_status_idx    ON chunks (status, access_level);
CREATE INDEX IF NOT EXISTS chunks_doc_type_idx  ON chunks (doc_type);

-- --- Request log (dashboard source) ---------------------------------------

CREATE TABLE IF NOT EXISTS requests (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  slack_user_id   TEXT NOT NULL,        -- ID only, never names or emails
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
  feedback_note   TEXT,
  cached          BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS requests_created_at_idx ON requests (created_at DESC);
CREATE INDEX IF NOT EXISTS requests_answered_idx   ON requests (answered);

-- --- Ingestion bookkeeping ------------------------------------------------

CREATE TABLE IF NOT EXISTS ingest_runs (
  id                    BIGSERIAL PRIMARY KEY,
  started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at           TIMESTAMPTZ,
  repo                  TEXT,
  files_seen            INT,
  files_indexed         INT,
  files_skipped_secrets INT,
  chunks_written        INT,
  chunks_deprecated     INT,
  status                TEXT,
  error                 TEXT
);

CREATE INDEX IF NOT EXISTS ingest_runs_started_idx ON ingest_runs (started_at DESC);

-- --- Small key/value store: docs version, cache ---------------------------

CREATE TABLE IF NOT EXISTS meta (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS answer_cache (
  cache_key     TEXT PRIMARY KEY,       -- sha256(normalized_question | docs_version)
  question      TEXT NOT NULL,
  docs_version  TEXT NOT NULL,
  payload       JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS answer_cache_created_idx ON answer_cache (created_at);

-- --- Read-only role for Metabase (spec section 14.7) ----------------------
-- Password must match METABASE_DB_PASSWORD in .env (default: change_me).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_ro') THEN
    CREATE ROLE metabase_ro LOGIN PASSWORD 'change_me';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE prodex TO metabase_ro;
GRANT USAGE ON SCHEMA public TO metabase_ro;
-- Deliberately NOT granted: SELECT on chunks (document content stays internal).
GRANT SELECT ON requests, ingest_runs TO metabase_ro;