# RawItem Ingestion v1 Live Acceptance

Environment: project-local PostgreSQL at `127.0.0.1:55432`; migration `20260712_0005`; 164 source definitions synchronized.

Three bounded fetch rounds were executed on 2026-07-12 with `uv run newsradar fetch --approved --max-items 5`. The latest round produced 14 successful/no-change targets: Google News, Techmeme, Bluesky, Hacker News, Mastodon, DeepMind, Hugging Face, OpenAI, arXiv cs.AI, BBC, Guardian, TechCrunch, The Verge and WIRED. RSS sources correctly reported `no_change` where conditional requests found no new content.

GDELT was not counted as successful: seven external failures (rate limits or remote disconnects) were recorded. Its adapter now reports HTTP 429 as `rate_limited`; it remains discovery-only and degraded.

Database evidence after the rounds: 138 RawItems and 93 FetchRuns. Upserts recorded inserted/updated/unchanged counts without duplicate RawItem identity. Google News retains discovery URLs and origin-resolution state; Bluesky/Mastodon retain interaction metrics. arXiv was repaired to preserve audited URL query fields while applying the bounded result limit.

Credential-gated Reddit/YouTube remain blocked unless their environment credentials are configured; this was verified by deterministic adapter tests rather than live credential use.
