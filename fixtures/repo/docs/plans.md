# Plans, limits and retention

## Plans

Atlas has three plans: **Starter**, **Business** and **Enterprise**. Features that differ
by plan are listed below; anything not listed is available on every plan.

| Capability | Starter | Business | Enterprise |
|---|---|---|---|
| Connected data sources | 1 | 5 | 25 |
| Dashboard users | 3 | 25 | Unlimited |
| SAML SSO | No | Yes | Yes |
| Google Workspace SSO | Yes | Yes | Yes |
| SCIM user provisioning | No | No | Yes |
| Scheduled exports | No | Weekly | Daily |
| Audit log | No | 90 days | 3 years |
| Uptime commitment | None | 99.9% | 99.95% |

## Data retention

Historical data is kept for a rolling window, measured from the end of the month:

- Starter: 13 months
- Business: 36 months
- Enterprise: 60 months

When a window rolls past, the data is deleted permanently. There is no archive tier.

## Seats

Adding a dashboard user is free on all plans. Seats are only counted for users who can
*edit* dashboards: Starter 3, Business 25, Enterprise unlimited.

## Trials

Every new workspace gets a 14-day Business trial with no credit card. A trial can be
extended once, for a further 14 days, by emailing `support@atlas.example`.

## Downgrades

Downgrading takes effect at the start of the next billing month. If the workspace has
more connected sources than the new plan allows, the extra sources are disconnected and
no data is deleted. Reconnecting them later requires the old plan.