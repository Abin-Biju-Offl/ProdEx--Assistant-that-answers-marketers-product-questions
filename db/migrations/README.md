# Migrations

**Phase 1 keeps one file: [`../schema.sql`](../schema.sql).**

Why: `db/schema.sql` is mounted into `docker-entrypoint-initdb.d`, so Postgres runs it on
first boot, and the API re-applies it on every start. Every statement is
`IF NOT EXISTS`, so re-running it is a no-op. A separate numbered-migration ledger would
be a second copy of the same DDL to keep in sync, with no benefit at this size.

**To change the schema in Phase 2+:** append idempotent DDL to `schema.sql`. Only
introduce numbered files here once you need ordered, non-idempotent migrations
(backfills, renames, drops) that must be applied exactly once and recorded.