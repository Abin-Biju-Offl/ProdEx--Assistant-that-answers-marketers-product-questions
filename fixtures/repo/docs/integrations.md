# Integrations

## Supported billing systems

| System | Supported | Read-only sync | Notes |
|---|---|---|---|
| Stripe | Yes | Yes | Subscription and one-off revenue |
| Chargebee | Yes | Yes | Subscription revenue |
| Recurly | Yes | Yes | Subscription revenue |
| Zuora | Enterprise only | Yes | Requires a solution engineer |
| Salesforce | Yes | Yes | Opportunity and account mapping |
| HubSpot | Yes | Yes | Company mapping only |
| NetSuite GL | Enterprise only | Yes | Journal entry mapping |

## Supported destinations

- **Google Sheets** — a daily snapshot lands in a sheet you nominate. Refresh is once
  per day, at 03:00 UTC.
- **Slack** — scheduled summary cards can be posted to a channel. Outbound only; Atlas
  does not read Slack.
- **Webhooks** — Atlas can push JSON to any HTTPS endpoint that returns 2xx.

## Webhook delivery guarantees

Webhooks are retried with exponential backoff: after 1 minute, then 5, 30, 2 hours and
24 hours. After the final attempt the event is dropped and the endpoint is moved to the
"paused" list in the admin console. A paused endpoint is retried manually, not
automatically.

Atlas does not sign webhook payloads in Phase 1. If you need to verify the sender,
allow-list the Atlas egress IPs published in the admin console.

## Not supported

- Two-way sync. Atlas never writes to a billing system.
- Custom connectors through the UI.
- Reading from data warehouses such as Snowflake or BigQuery.