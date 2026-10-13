# Product Truths

Hand-written, engineer-approved answers to the questions marketers ask most. Each `## `
heading is one fact. Keep each answer under three lines: this content is retrieved
verbatim and has the highest priority in search.

## Does Atlas support single sign-on?

**Answer:** Yes. SAML 2.0 SSO is available on Business and Enterprise. Google Workspace
SSO works on every plan. SCIM automatic user provisioning is Enterprise only.
**Source:** docs/plans.md
**Owner:** platform-team

## Is there an on-premise or self-hosted version of Atlas?

**Answer:** No. Atlas is cloud only. On-premise installation is not available and is not
planned. This is a firm answer; do not offer an exception or a pilot.
**Source:** README.md
**Owner:** product-leadership

## What is the API rate limit?

**Answer:** 100 requests per minute per workspace, on every plan, shared across all keys
and endpoints. Short bursts of up to 20 requests per second are tolerated for up to five
seconds.
**Source:** docs/limits.md
**Owner:** platform-team

## How many rows can one export contain?

**Answer:** 250,000 rows, header row included. Larger exports fail with EXP-4291. The
workaround is to split the date range and export each window separately.
**Source:** docs/export.md
**Owner:** reporting-team

## Which export formats are supported?

**Answer:** CSV and XLSX only. There is no PDF export and no scheduled PDF. The only PDF
output is a browser print of the dashboard, which is currently blank in Safari 16.
**Source:** docs/export.md
**Owner:** reporting-team

## Which timezones do exports use?

**Answer:** Exports are always written in UTC. The dashboard shows the workspace timezone.
An export includes a utc_offset_note column so the difference can be explained.
**Source:** docs/export.md
**Owner:** reporting-team

## How long is data kept?

**Answer:** 13 months on Starter, 36 months on Business, 60 months on Enterprise. There is
no archive tier; data past the window is deleted permanently.
**Source:** docs/plans.md
**Owner:** platform-team

## Is there a mobile app?

**Answer:** No native mobile app. The web app is responsive and works in a mobile
browser, but there is no offline mode and no app-store build.
**Source:** README.md
**Owner:** product-leadership

## Does Atlas do forecasting?

**Answer:** No, not today. Forecasting is on the roadmap but is planned, not committed, and
has no date. Never promise a forecasting date.
**Source:** README.md
**Owner:** product-leadership

## Can Atlas write back to our billing system?

**Answer:** No. Every integration is read-only. Atlas never creates, updates or deletes
anything in a customer's billing system or CRM.
**Source:** docs/integrations.md
**Owner:** platform-team

## Which CRMs does Atlas connect to?

**Answer:** Salesforce and HubSpot. Zuora and NetSuite are Enterprise only and need a
solution engineer. There is no marketplace connector builder.
**Source:** docs/integrations.md
**Owner:** platform-team

## How fast is support?

**Answer:** First response is 2 business days on Starter, 1 business day on Business and
4 hours on Enterprise. Support email is support@atlas.example.
**Source:** README.md
**Owner:** customer-success

## What uptime do we commit to?

**Answer:** 99.9% on Business and 99.95% on Enterprise, measured monthly. Starter has no
uptime commitment.
**Source:** docs/plans.md
**Owner:** platform-team

## Why do dashboard numbers not match the billing system?

**Answer:** Atlas syncs once a day at 03:00 UTC. Changes made during the day appear after
the next sync. Check the "last synced" timestamp before treating it as a bug.
**Source:** docs/troubleshooting.md
**Owner:** support-team

## What are the known bugs right now?

**Answer:** Three open bugs: blank PDF print in Safari 16, Salesforce customer names
showing billing IDs on multi-currency accounts, and Google Sheets snapshots arriving a day
late in UTC+13 and UTC-11 workspaces. The first two are fixed in 2.5.0.
**Source:** docs/troubleshooting.md
**Owner:** support-team

## What facts should support collect before escalating?

**Answer:** What the customer did step by step, the exact error message copied rather than
typed, the device browser and app version, and when it started and whether it worked
before.
**Source:** docs/troubleshooting.md
**Owner:** support-team