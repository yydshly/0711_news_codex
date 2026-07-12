# Milestone B Security Fix Report

## Scope

- Redirect resolution now DNS-resolves every HTTPS hop immediately before its request and rejects any non-global IPv4 or IPv6 answer, including loopback, private, link-local, multicast, and documentation/reserved ranges.
- Resolver redirects use the existing `HttpPolicy` semaphore path and filter configured headers through `public_headers`.
- GDELT treats all article metadata as discovery-only. Publisher attribution is populated only from `OriginResolver` confirmation; resolver failure remains unresolved.
- Google News and GDELT filter cookies, authorization, API-key, token, secret, and credential-like headers before issuing public-source requests.
- Enabled ingestion configurations now require `approved_at`, matching the README policy.

## DNS-rebinding limitation

HTTPX's public client API does not permit connecting to a previously validated IP while retaining the URL hostname for HTTPS SNI and certificate verification. The resolver therefore resolves and validates immediately for every hop and fails closed for lookup failures, but cannot pin the subsequent HTTPX socket without a custom transport. This limitation is documented beside the resolver call; do not treat hostname resolution as full DNS-rebinding protection.

## Verification

- Focused resolver, Google News, GDELT, and schema tests passed.
- Full suite passed: `262 passed` (with existing FastAPI and Alembic deprecation warnings).
- `ruff check .` passed.
