# RawItem Ingestion v1 Final Acceptance

## Completed evidence

- Registry and source universe: 67 providers and 164 targets, with 15 audited free active targets across official, media, aggregation and social/community layers.
- Ingestion: RSS/Atom, GitHub, Hacker News, arXiv, Bluesky, Mastodon, Google News, GDELT plus official credential-gated Reddit/YouTube adapters.
- Reliability: lease recovery, non-owner protection, heartbeat updates, nonblocking web operation creation and diagnostics are covered by acceptance tests and `reports/raw-item-ingestion-reliability.md`.
- Operations UI: local-only, same-origin, CSRF and one-time idempotency-protected enqueue; status, content, versions, duplicates and system health are visible without executing fetch work in a request.
- Live evidence: `reports/raw-item-ingestion-live-acceptance.md`.

## External blockers

GDELT is degraded by provider-side rate limits/disconnects and is not counted as a stable source. Restricted social platforms remain cataloged but intentionally blocked until official permissions/credentials are provided.

## Quality gate

Run `uv run ruff check .` and `uv run pytest -q` before integration. Verify migrations reach head, local web routes return 200, and diagnostics contain no credentials. Do not merge while unrelated user worktree changes remain unstaged.
