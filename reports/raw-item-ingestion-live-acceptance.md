# RawItem Ingestion v1 Live Acceptance

## Scope and reproducibility

Environment recorded in the project report: project-local PostgreSQL at
`127.0.0.1:55432`, migration `20260712_0005`, and 164 synchronized source
definitions. The bounded command used for the approved-source batches was:

```powershell
uv run newsradar fetch --approved --max-items 5
```

All timestamps below are database `fetch_runs.started_at` / `finished_at`,
America/Los_Angeles (UTC−07:00). A usable result is `succeeded` or `no_change`;
`no_change` with HTTP 304 is a successful conditional-fetch outcome, not a
failure. This report deliberately does **not** convert scattered successful
runs into a claim of three complete rounds.

## What the recorded database proves

The final 14-target approved batches in the database are below. Hacker News
Best was run separately as the webpage-to-worker acceptance path; it was not
part of either complete 14-target batch. Therefore the current evidence is
insufficient to certify “three complete rounds for all 15 stable targets”. A
fresh three-round 15-target run is still required before final Milestone D
acceptance.

| Target | Batch 1: 2026-07-12 03:21:50–03:22:12 | Batch 2: 2026-07-12 03:26:46–03:27:25 | Separate HN Best evidence | Honest status |
|---|---|---|---|---|
| `bluesky-bsky` | run 63, 03:21:50.462–03:21:50.560, succeeded, received 5 / inserted 5 | run 79, 03:26:56.072–03:26:56.183, succeeded, received 5 / inserted 5 | — | two usable batch results |
| `google-news-ai` | run 65, 03:21:51.208–03:21:51.271, succeeded, 5 / 3 inserted / 2 unchanged | run 81, 03:26:56.684–03:26:56.729, succeeded, 5 / 1 inserted / 4 unchanged | — | two usable batch results |
| `techmeme-feed` | run 64, 03:21:50.928–03:21:50.932, no_change, HTTP 304 | run 80, 03:26:56.543–03:26:56.557, no_change, HTTP 304 | — | two usable conditional results |
| `mastodon-mastodon` | run 66, 03:21:52.426–03:21:52.514, succeeded, 5 / 5 inserted | run 82, 03:26:57.779–03:26:57.882, succeeded, 5 / 5 inserted | — | two usable batch results |
| `deepmind-blog` | run 67, 03:21:53.382–03:21:53.507, succeeded, 5 / 5 inserted | run 83, 03:26:58.210–03:26:58.222, no_change, HTTP 304 | — | two usable results |
| `hackernews-top` | run 68, 03:21:53.703–03:21:53.746, succeeded, 5 / 1 inserted / 4 unchanged | run 85, 03:26:59.283–03:26:59.346, succeeded, 5 / 0 inserted / 5 unchanged | — | two usable batch results |
| `huggingface-blog` | run 69, 03:21:54.089–03:21:54.174, succeeded, 5 / 5 inserted | run 84, 03:26:58.963–03:26:58.976, no_change, HTTP 304 | — | two usable results |
| `arxiv-cs-ai` | run 70, 03:21:54.943–03:21:54.952, **failed**, HTTP 400 (`max_results` overwrote query) | run 78, 03:26:46.468–03:26:46.600, succeeded, 5 / 5 inserted; run 86, 03:26:59.862–03:26:59.905, succeeded, 5 / 5 unchanged | — | repair verified after one recorded failure |
| `universe-bbc-1` | run 71, 03:21:55.166–03:21:55.191, succeeded, 5 / 0 inserted / 5 unchanged | run 88, 03:27:00.254–03:27:00.284, succeeded, 5 / 0 inserted / 5 unchanged | — | two usable batch results |
| `openai-news` | run 72, 03:21:55.811–03:21:55.936, succeeded, 5 / 5 inserted | run 87, 03:27:00.181–03:27:00.243, succeeded, 5 / 0 inserted / 5 unchanged | — | two usable batch results |
| `universe-techcrunch-1` | run 73, 03:21:56.144–03:21:56.150, no_change, HTTP 304 | run 90, 03:27:01.142–03:27:01.146, no_change, HTTP 304 | — | two usable conditional results |
| `universe-wired-1` | run 74, 03:21:56.809–03:21:56.864, succeeded, 5 / 1 inserted / 4 unchanged | run 92, 03:27:01.731–03:27:01.769, succeeded, 5 / 0 inserted / 5 unchanged | — | two usable batch results |
| `universe-guardian-1` | run 75, 03:21:56.936–03:21:56.961, succeeded, 5 / 0 inserted / 5 unchanged | run 91, 03:27:01.593–03:27:01.641, succeeded, 5 / 1 inserted / 4 unchanged | — | two usable batch results |
| `universe-the-verge-1` | run 76, 03:21:57.243–03:21:57.249, no_change, HTTP 304 | run 89, 03:27:00.935–03:27:00.943, no_change, HTTP 304 | — | two usable conditional results |
| `hackernews-best` | not in this batch | not in this batch | runs 94/95/96: 03:43:43.089–03:43:43.206 inserted 5; 03:43:54.193–03:43:54.253 unchanged 5; 03:43:58.389–03:43:58.508 unchanged 5 | three usable isolated runs; not full-round proof |
| `gdelt-ai` | run 77, 03:22:12.426–03:22:12.436, **failed**: remote disconnect | run 93, 03:27:25.742–03:27:25.747, **failed** (external failure) | — | degraded, excluded from stable counts |

## Database evidence and interpretation

Snapshot after these runs: 96 `fetch_runs`, 143 `raw_items`, and zero duplicate
`(source_id, external_id)` identities. The database showed 30/30 stored items
with non-null engagement for each of Bluesky and Mastodon at query time, and
5/5 for Hacker News Best plus 8/8 for Hacker News Top. Google News stored 10
items with `origin_resolution_status = unresolved`; its discovery links must not
be treated as original-publisher evidence until resolution succeeds.

The browser-to-worker acceptance execution is separately reproducible as:

```powershell
# create the local, same-origin operation in the web UI, then:
uv run newsradar worker --once --worker-id acceptance-worker
```

Recorded result: operation 14 was consumed and produced fetch run 94 for
`hackernews-best`, with five inserted items. This validates the enqueue → worker
→ FetchRun → RawItem path; it does not replace a full, timestamped three-round
source-health run.

## External and credential-gated results

GDELT has eight recorded runs: one usable and seven failed. Recorded external
failures include HTTP 429 and remote disconnects; it remains discovery-only,
degraded, and excluded from stable-source counts. Reddit and YouTube were not
live-fetched because required official credentials are absent; their blocked
state is validated by deterministic adapter tests rather than fabricated live
success.

## Remaining acceptance command

After the Worker lease/retry changes are merged, run the bounded command above
three times against the exact 15 enabled target IDs, record each run ID and
timestamp in this table, and retain GDELT as a separately reported degraded
source. Only then may the project claim three complete stable-source rounds.
