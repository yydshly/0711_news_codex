# Open-source ingestion target review

Reviewed: 2026-07-11. This matrix contains only enabled, bounded, public targets. Identity and
endpoint evidence are direct official URLs recorded in the source YAML; no generated placeholder
URL was enabled.

| Target | Class | Identity evidence | Endpoint evidence | Role / attribution mode | Risk | Reviewed / approved |
| --- | --- | --- | --- | --- | ---: | --- |
| `universe-bbc-1` | professional media | BBC Technology | BBC Technology RSS | evidence; direct publisher feed | 6/25 | 2026-07-11 / 2026-07-11 |
| `universe-guardian-1` | professional media | The Guardian Technology | The Guardian Technology RSS | evidence; direct publisher feed | 8/25 | 2026-07-11 / 2026-07-11 |
| `universe-wired-1` | professional media | WIRED | WIRED RSS | evidence; direct publisher feed | 6/25 | 2026-07-11 / 2026-07-11 |
| `universe-the-verge-1` | professional media | The Verge | The Verge RSS | evidence; direct publisher feed | 6/25 | 2026-07-11 / 2026-07-11 |
| `universe-techcrunch-1` | professional media | TechCrunch | TechCrunch Feed | evidence; direct publisher feed | 6/25 | 2026-07-11 / 2026-07-11 |
| `gdelt-ai` | aggregator | GDELT Project | GDELT DOC 2.0 API | discovery; preserve discovery URL and original-publisher attribution | 11/25 | 2026-07-11 / 2026-07-11 |
| `techmeme-feed` | aggregator | Techmeme | Techmeme Feed | discovery; resolve linked publisher before evidence use | 9/25 | 2026-07-11 / 2026-07-11 |
| `google-news-ai` | aggregator | Google News | Google News RSS | discovery; preserve Google URL and resolve publisher before evidence use | 10/25 | 2026-07-11 / 2026-07-11 |
| `hackernews-top` | community | Hacker News | Official Firebase API | discovery, engagement, context; discussion is not evidence | 5/25 | 2026-07-11 / 2026-07-11 |
| `bluesky-bsky` | social | Bluesky official account | AppView author-feed method | discovery, engagement, context; account/post identity retained | 6/25 | 2026-07-11 / 2026-07-11 |
| `mastodon-mastodon` | social | Mastodon official account | Mastodon account-statuses method | discovery, engagement, context; instance-qualified account/status identity retained | 7/25 | 2026-07-11 / 2026-07-11 |

Professional-media feeds may contribute evidence under their recorded roles. Aggregator and
social/community records do not become evidence merely because they are ingested: their original
publisher or independently corroborating source must carry that role. All targets use conservative
five-item runs and have no alternate automated fallback.
