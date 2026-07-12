# RawItem Ingestion v1 Target Matrix

Audited on 2026-07-12. The active free matrix contains 15 targets: OpenAI, DeepMind, Hugging Face, arXiv cs.AI, BBC, Guardian, TechCrunch, The Verge, WIRED, Techmeme, Google News, GDELT, Hacker News, Bluesky and Mastodon.

| Layer | Targets | Method | Role | Decision |
|---|---|---|---|---|
| Official / developer | OpenAI News, DeepMind Blog, Hugging Face Blog, arXiv cs.AI | RSS/Atom | discovery, evidence | active; free and reviewed |
| Professional media | BBC, Guardian, TechCrunch, The Verge, WIRED | RSS | discovery, context | active; attribution retained |
| Aggregator | Google News, Techmeme, GDELT | RSS/public API | discovery only | Google News/Techmeme active; GDELT degraded by external rate/disconnect failures |
| Social / community | Hacker News, Bluesky, Mastodon | public APIs | discovery, engagement | active; never sole fact evidence |

All active targets use HTTPS, reviewed identity URLs, an audited first method, explicit fallback/no-fallback notes, language/topics/roles and scored risk in YAML. Restricted targets remain cataloged but blocked: X (`requires_payment`), Facebook/Instagram/Threads (`requires_approval`), TikTok (`requires_approval`), LinkedIn (`requires_approval`), Reddit/YouTube (`requires_credentials`). They are excluded from successful-fetch counts and no cookie/login scraping is used.
