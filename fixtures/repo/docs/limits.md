# API rate limits

## The numbers

The Atlas API allows **100 requests per minute per workspace** on every plan. The limit
is shared across all endpoints and all API keys belonging to the workspace.

Short bursts are tolerated: you may send up to **20 requests per second** for up to five
consecutive seconds. Beyond that you are rate limited even if your per-minute count is
under 100.

## What happens when you hit the limit

Every response carries the headers `X-RateLimit-Limit`, `X-RateLimit-Remaining` and
`X-RateLimit-Reset` (Unix seconds). Once you exceed the limit, the API returns
`429 Too Many Requests` and a `Retry-After` header.

## Raising the limit

Business and Enterprise workspaces can request a higher limit by emailing
`api@atlas.example` with the workspace ID and the number of requests per minute you
need. Starter workspaces cannot raise the limit in Phase 1.

## Authentication

API keys are read-only. There is no write endpoint. Key rotation is immediate: create a
second key, deploy it, then revoke the first. Revocation takes effect within 60 seconds.