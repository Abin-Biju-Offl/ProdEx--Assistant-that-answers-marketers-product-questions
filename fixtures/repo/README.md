# Atlas

Atlas is a revenue reporting tool for subscription businesses. It connects to your
billing system, keeps a daily snapshot of your numbers, and gives finance and sales a
dashboard they can actually use without an analyst.

- **Audience:** finance managers, sales leads and customer success managers.
- **Shape:** a web app at `app.atlas.example` plus a read-only REST API.
- **Data:** Atlas reads from your billing system. Atlas never writes back to it.

## What Atlas does

- Daily revenue, MRR, churn and expansion metrics per customer and per segment.
- Board-ready exports to CSV and XLSX.
- A read-only REST API and webhooks for downstream reporting.

## What Atlas does not do

Atlas does not process payments, does not send invoices, and does not do forecasting.
Forecasting is on the roadmap but is **not committed** to any date.

## Getting help

| Plan | Channel | First response |
|---|---|---|
| Starter | Email only | 2 business days |
| Business | Email + live chat | 1 business day |
| Enterprise | Email + live chat + phone | 4 hours |

Support email is `support@atlas.example`. Product questions belong in the
`#atlas-product` Slack channel.

## Where the detail lives

- [Getting started](docs/getting-started.md)
- [Plans and limits](docs/plans.md)
- [API rate limits](docs/limits.md)
- [Exports](docs/export.md)
- [Integrations](docs/integrations.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Product truths](docs/PRODUCT_TRUTHS.md)