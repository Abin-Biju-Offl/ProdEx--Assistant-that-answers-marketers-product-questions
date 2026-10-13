# 2. Webhook retries stop after five attempts

Date: 2026-05-19

## Context

Customers reported that webhook payloads stopped arriving with no warning. Investigation
showed the retry scheduler skipped the fourth and fifth attempts, so an endpoint that was
down for two hours never received the events it missed.

## Decision

Webhooks are retried at 1 minute, 5 minutes, 30 minutes, 2 hours and 24 hours, and then
the endpoint is moved to the "paused" list in the admin console.

## Consequences

- A paused endpoint is never retried automatically. Recovery is a manual action, which is
  a real operational cost for customers and is a known complaint.
- We do not sign payloads. Customers who need to verify the sender must allow-list the
  Atlas egress IPs. Adding payload signing is on the roadmap but not committed.
- Dropped events are logged for 30 days and can be re-sent manually from the admin
  console.