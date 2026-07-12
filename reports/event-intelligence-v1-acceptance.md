# Event Intelligence v1 Acceptance Evidence

Date: 2026-07-12
Acceptance baseline commit: `475ee616f41468bda049027563135e1ee5120f07`
Database migration: `20260712_0008 (head)`

## Automated gate

`uv run alembic upgrade head` and `uv run alembic current` reported the revision above. `uv run
ruff check .` completed with no violations. The full suite completed with the project `.env`
temporarily removed from test discovery so optional local credentials could not change
credential-absence tests; it was restored immediately: 459 passed, 3 skipped.

Dedicated release checks passed:

```powershell
uv run pytest tests/acceptance/test_event_web_worker_flow.py `
  tests/acceptance/test_event_postgres_contention.py `
  tests/acceptance/test_event_model_degradation.py -q
```

Result: 3 passed. They cover web enqueue -> durable Worker -> published event detail, a real
PostgreSQL expired-lease recovery, and MiniMax-off fallback with no HTTP call.

## Real-data rounds

Approved-source fetch work was queued before the event rounds. Its Worker operations reached
terminal state, but `fetch --wait` then raised `DetachedInstanceError` while printing terminal
rows; see known gaps. No credentials, feed bodies, or upstream error URLs are included.

| Round | Operation | Window | Relevant / candidates | Published IDs / new versions | Status split | Model calls |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| 1 | 104 | 24h | 2 / 2 | 1, 2 / 2 | emerging 2; confirmed 0; disputed 0 | 0 |
| 2 | 105 | 24h | 2 / 2 | 1, 2 / 0 | emerging 2; confirmed 0; disputed 0 | 0 |
| 3 | 106 | 24h | 2 / 2 | 1, 2 / 0 | emerging 2; confirmed 0; disputed 0 | 0 |

All three operations succeeded. Repeated IDs and zero new versions in rounds 2 and 3 are replay
evidence. Persisted summaries do not expose duplicate-root suppression, retry totals, duration, or
model-fallback counters, so those values are intentionally not claimed.

### Model-off round

Operation 108 was a standard 24-hour build consumed by a one-shot Worker launched with
`MINIMAX_API_KEY` absent while preserving only the required local database connection. It
succeeded, returned IDs 1 and 2, created zero versions, and recorded zero model runs. The dedicated
test additionally proves the no-key path makes no HTTP request and returns `rule_fallback`.

### Separate 7-day category check

Because the 24-hour input lacked the four target categories, acceptance-only operation 107 used
`--hours 168`; the homepage product window remains 24 hours. It succeeded with 9 relevant items /
candidates, IDs 1 through 9, and 7 new versions; status was confirmed 2 and emerging 7. All nine
stored events have null category, so four-category coverage remains unproven.

## Browser-ready acceptance

The worktree was served on a non-conflicting loopback port while a Worker was active. Textual
route checks were HTTP 200: `/` (2,396 bytes), `/events` (3,247), `/emerging` (2,781), `/events/1`
(3,297), and `/operations/104` (2,997). Detail ID 1 retained original-link traceability. No
screenshot was captured; status and rendered-byte checks are the textual browser evidence.

## Known gaps and review focus

- `newsradar fetch --wait` has a post-completion detached-instance failure while rendering status.
- Real 24-hour and 7-day data did not establish category coverage.
- Operation summaries omit duration, duplicate-root, retry, and model-fallback counters.
- The actual migration head is `20260712_0008`; the brief expected `20260712_0007`.

## Final-review reproducibility update

The final regression suite uses an isolated environment: `.env` is moved aside in a `try/finally`
block and restored immediately afterwards. The deterministic fixture suite now covers product/model,
research, developer-tool, and company category inputs when live inputs do not supply all four.
The real-data limitation remains transparent: the recorded live rounds did not establish all four
categories.

Operation summaries now record the bounded counters required for reruns: duration, retry count,
duplicate-root suppression, and model-fallback count. The final run duration and retry values must
be taken from the terminal operation records; no invented live values are included here.
