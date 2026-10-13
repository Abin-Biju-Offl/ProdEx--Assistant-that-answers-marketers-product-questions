# Exports

## What can be exported

Atlas exports two formats:

- **CSV** — UTF-8, comma separated, one header row.
- **XLSX** — one sheet per selected segment, formatted for spreadsheets.

## Size limits

A single export is limited to **250,000 rows**. Larger exports fail with the error code
`EXP-4291` and the message "Export exceeds row limit".

The row count includes the header row. The practical ceiling is therefore 249,999 data
rows per export.

## Workaround for large exports

Split the date range into smaller windows and export each window separately. Exports
can be run in parallel, up to three at a time. Linking the resulting files is the
customer's responsibility; Atlas does not concatenate them.

## Scheduled exports

| Plan | Frequency |
|---|---|
| Starter | Not available |
| Business | Weekly |
| Enterprise | Daily |

A scheduled export always uses the formats and date range chosen at scheduling time. To
change them, edit the schedule and save; the change applies from the next run.

## Delivery

Scheduled exports are emailed as a download link that expires after 7 days. The link is
not password protected; anyone with the link can download the file, so treat it like a
password.

## Timezones in exports

Exports are always written in **UTC**. The dashboard displays figures in the workspace
timezone, so numbers can look different between the dashboard and an export. Exports
include a `utc_offset_note` column stating the offset that was applied.