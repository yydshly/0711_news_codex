# RawItem Ingestion v1 Live Acceptance

Environment: project-local PostgreSQL at `127.0.0.1:55432`; migration `20260712_0005`; 164 source definitions synchronized.

Three bounded fetch rounds were executed on 2026-07-12 with `uv run newsradar fetch --approved --max-items 5`. The stable free set contains 15 successful/no-change targets: Google News, Techmeme, Bluesky, Hacker News Top, Hacker News Best, Mastodon, DeepMind, Hugging Face, OpenAI, arXiv cs.AI, BBC, Guardian, TechCrunch, The Verge and WIRED. RSS sources correctly reported `no_change` where conditional requests found no new content.

| Round | Evidence | Result |
|---|---|---|
| 1 | initial bounded approved fetch | open-source baseline persisted |
| 2 | repeated approved fetch | conditional/no-change and idempotent upsert evidence |
| 3 | approved fetch plus `hackernews-best` end-to-end worker operation | 15 stable targets; operation 14 succeeded |

GDELT was not counted as successful: seven external failures (rate limits or remote disconnects) were recorded. Its adapter now reports HTTP 429 as `rate_limited`; it remains discovery-only and degraded.

Database evidence after the rounds: 143 RawItems and 96 FetchRuns. Upserts recorded inserted/updated/unchanged counts without duplicate RawItem identity. Google News retains discovery URLs and origin-resolution state; Bluesky/Mastodon retain interaction metrics. arXiv was repaired to preserve audited URL query fields while applying the bounded result limit. A browser-session POST created operation 14; `newsradar worker --once --worker-id acceptance-worker` consumed it and persisted fetch run 94 with five inserted items.

Credential-gated Reddit/YouTube remain blocked unless their environment credentials are configured; this was verified by deterministic adapter tests rather than live credential use.
