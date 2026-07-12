# RawItem Ingestion v1 Target Matrix

Audited on 2026-07-12. The catalog audit covers 20 reviewed targets; the stable free fetch set contains 15 targets after replacing degraded GDELT with Hacker News Best.

| Layer | Targets | Method | Role | Decision |
|---|---|---|---|---|
| Official / developer | OpenAI News, DeepMind Blog, Hugging Face Blog, arXiv cs.AI | RSS/Atom | discovery, evidence | active; free and reviewed |
| Professional media | BBC, Guardian, TechCrunch, The Verge, WIRED | RSS | discovery, context | active; attribution retained |
| Aggregator | Google News, Techmeme, GDELT | RSS/public API | discovery only | Google News/Techmeme active; GDELT degraded by external rate/disconnect failures |
| Social / community | Hacker News, Bluesky, Mastodon | public APIs | discovery, engagement | active; never sole fact evidence |

| Reviewed target | Endpoint/method | Availability / cost | Risk | Conclusion |
|---|---|---|---:|---|
| OpenAI News | openai.com/news/rss.xml RSS | ready / free | 3 | active |
| DeepMind Blog | deepmind.google/blog/rss.xml RSS | ready / free | 3 | active |
| Hugging Face Blog | huggingface.co/blog/feed.xml RSS | ready / free | 3 | active |
| arXiv cs.AI | export.arxiv.org Atom | ready / free | 4 | active |
| BBC Technology | BBC RSS | ready / free | reviewed | active |
| Guardian Technology | Guardian RSS | ready / free | reviewed | active |
| TechCrunch | TechCrunch RSS | ready / free | reviewed | active |
| The Verge | The Verge RSS | ready / free | reviewed | active |
| WIRED | WIRED RSS | ready / free | reviewed | active |
| Techmeme | techmeme.com/feed.xml RSS | ready / free | reviewed | active discovery |
| Google News AI | Google News RSS | ready / free | reviewed | active discovery |
| Hacker News Top | Firebase public API | ready / free | reviewed | active |
| Hacker News Best | Firebase public API | ready / free | reviewed | active |
| Bluesky | AppView public API | ready / free | reviewed | active engagement |
| Mastodon | public API | ready / free | reviewed | active engagement |
| GDELT | public API | ready / free | reviewed | degraded; not stable |
| Reddit | OAuth API | credentials / quota | reviewed | blocked pending approval |
| YouTube | Data API | credentials / quota | reviewed | blocked pending key |
| X | official API | payment | reviewed | catalog only |
| Threads | official API | approval | reviewed | catalog only |

All active targets use HTTPS, reviewed identity URLs, an audited first method, explicit fallback/no-fallback notes, language/topics/roles and scored risk in YAML. Restricted targets remain cataloged but blocked: X (`requires_payment`), Facebook/Instagram/Threads (`requires_approval`), TikTok (`requires_approval`), LinkedIn (`requires_approval`), Reddit/YouTube (`requires_credentials`). They are excluded from successful-fetch counts and no cookie/login scraping is used.
