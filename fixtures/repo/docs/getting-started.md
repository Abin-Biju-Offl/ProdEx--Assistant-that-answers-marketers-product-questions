# Getting started

## Connect a billing system

1. Open **Settings > Data sources**.
2. Choose your billing system and authorise it.
3. Atlas runs a first sync immediately. A typical workspace finishes in under an hour.
4. The dashboard becomes available once the sync completes.

Only one billing system can be primary at a time. Additional sources appear as segments
and are labelled with the source name in every chart.

## Invite the team

Dashboard users are invited by email. There is no domain capture: an invitation must be
sent to each address individually, unless your plan includes SAML SSO, in which case
users sign in through your identity provider and are created on first sign-in.

## Build the first dashboard

The default dashboard shows revenue, MRR, churn and expansion. Duplicate a card, or add
one from the card library. Every card has a date range, a segment filter and a comparison
mode.

## Understand "last synced"

Every dashboard shows the timestamp of the last successful sync, in UTC and in the
workspace timezone. If that timestamp is more than 26 hours old, the sync is failing and
should be raised with support before anything else.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `g d` | Go to dashboard |
| `g s` | Go to settings |
| `/` | Open the date picker |
| `?` | Show the shortcut list |