# 1. Use Postgres for the analytics store

Date: 2026-03-04

## Context

Atlas needs to answer revenue questions over 60 months of subscription data. The data
arrives once a day as a batch from the billing system, and the read pattern is almost
always "aggregate by month, segment and currency".

## Decision

Store the analytics data in Postgres 16 using pre-aggregated monthly tables, rather than
introducing a dedicated warehouse.

## Consequences

- One system to operate, one set of backups, no second vendor to pay.
- Aggregations over 60 months are fast enough for the dashboard because we pre-aggregate
  on ingest rather than scanning raw events at read time.
- If Atlas grows past roughly 10,000 workspaces we will need to revisit this. The
  aggregation tables partition by workspace, so the migration is a copy rather than a
  rewrite.
- Analysts lose the ability to run ad-hoc SQL against raw events through a SQL console.
  Pre-aggregated tables only. This was accepted deliberately.