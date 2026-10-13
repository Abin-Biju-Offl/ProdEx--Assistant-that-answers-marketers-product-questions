# Troubleshooting

Use this page to answer customers. If the cause is not listed, collect the four facts in
"Before escalating" and send them to engineering.

## Reports look wrong

### Figures differ from the billing system

Atlas refreshes once a day at 03:00 UTC. If the billing system was changed during the
day, the dashboard will not reflect it until the next refresh. Check the "last synced"
timestamp at the top of the dashboard before treating a difference as a bug.

### Month-to-date numbers look lower than expected

Month-to-date figures exclude refunds issued in the same period if the refund was
processed after 03:00 UTC. This is working as designed.

### The dashboard shows last month's figures

The workspace timezone is ahead of UTC and the day has not rolled over in UTC yet. Wait
for the UTC date to change, or change the workspace timezone in settings.

## Exports fail

### "Export exceeds row limit" (EXP-4291)

The export is over 250,000 rows. Split the date range and export each window separately.
See [Exports](export.md).

### The download link has expired

Scheduled export links expire after 7 days. Re-run the export from the exports page.

### An XLSX export will not open in Excel

Files over roughly 100,000 rows sometimes fail to open in older Excel versions. Export
CSV instead, or split the export.

## API errors

### 429 Too Many Requests

You have passed 100 requests per minute for the workspace. Check the `Retry-After`
header and wait. See [API rate limits](limits.md).

### 401 on a key that used to work

The key was revoked or rotated. Revocation takes effect within 60 seconds.

### 403 with "scope missing"

The key is read-only and the endpoint requires a write scope. There is no write endpoint
in the API today; email `api@atlas.example` if you believe one is needed.

## Known bugs

| Symptom | Environment | Status |
|---|---|---|
| PDF print of any dashboard is blank | Safari 16 and 16.1 | Open, fix due in 2.5.0 |
| Customer name shows a billing-system ID | Salesforce sync, multi-currency accounts | Open, fix due in 2.5.0 |
| Google Sheets snapshot arrives a day late | Workspace in UTC+13 or UTC-11 | Open, fix due in 2.6.0 |

## Before escalating

Collect all four:

1. What the customer was doing, step by step.
2. The exact error message, copied not typed.
3. Device, browser and Atlas app version.
4. When it started, and whether it worked before.