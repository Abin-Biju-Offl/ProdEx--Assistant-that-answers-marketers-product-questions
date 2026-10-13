# Changelog

All notable changes to Atlas are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/).

## [2.4.1] - 2026-09-28

### Fixed

- Scheduled exports now include the `utc_offset_note` column that the documentation
  already promised.
- Churn cards no longer double-count a refund that was processed after the 03:00 UTC
  sync on the day it was issued.

## [2.4.0] - 2026-09-15

### Added

- Dashboard users can be created automatically on first SAML sign-in on Enterprise plans.
- A "last synced" indicator now appears on every dashboard, in UTC and in the workspace
  timezone.

### Changed

- The sync window moved from 04:00 UTC to 03:00 UTC. Workspaces that relied on the old
  window see figures roughly an hour earlier.

## [2.3.0] - 2026-08-20

### Added

- NetSuite General Ledger became available on Enterprise plans, with journal entry
  mapping. It requires a solution engineer.

### Fixed

- Webhook retries now follow the documented backoff of 1 minute, 5 minutes, 30 minutes,
  2 hours and 24 hours. Previously the fourth and fifth attempts were skipped.

## [2.2.1] - 2026-07-30

### Fixed

- Google Sheets snapshots for workspaces in UTC+13 and UTC-11 were arriving a day late.
  A fix is scheduled for 2.6.0.

## [2.2.0] - 2026-06-11

### Added

- SCIM user provisioning on Enterprise plans.
- Audit log retention raised from 90 days to 3 years on Enterprise.

### Removed

- The legacy v1 API. v1 stopped accepting requests on 2026-06-11. Clients that had not
  migrated received three months of email warnings between March and June 2026.