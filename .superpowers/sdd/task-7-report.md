# Task 7 report — Chinese event intelligence web

## Delivered

- Replaced `/` with the recent, confirmed-event home and preserved the prior source dashboard at `/sources`.
- Added `/events`, `/events/{id}`, and `/emerging` read views backed by a read-only `EventQueryService`.
- Event pages show Chinese summaries, status separation, heat/score reasons, original evidence links, evidence roles, timeline timestamps, algorithm version, and a MiniMax fallback banner.
- Added safe POST entry points for building, reclustering, enriching, excluding, merging, and splitting events. They call the existing one-time-token/origin checks and only enqueue durable operations with `actor: web` in scope.
- Added event query and route tests; updated source-dashboard tests for its new `/sources` URL.

## Verification

- `uv run pytest tests/web/test_event_queries.py tests/web/test_event_routes.py tests/web/test_routes.py tests/web/test_security.py -q` — 53 passed.
- With `.env` hidden and restored: `uv run pytest -q` — passed (two existing skips).
- `uv run ruff check .` — passed.

## Note

No browser server was launched for this subtask; coverage is browser-ready template and route testing. The web process imports no HTTPX or MiniMax client and event writes stay in the durable operation boundary.

## Review remediation (RED/GREEN)

- RED: `test_supported_web_action_is_nonretryable_until_its_mutation_is_implemented` observed `event_recluster` completing successfully without mutation; `test_merge_validates_both_event_targets_before_returning_unsupported` observed a missing merge target ignored; the safe-link projection test retained `javascript:` URLs.
- GREEN: unsupported event action types now validate their complete durable scope in the worker, then fail once with nonretryable `unsupported_action` instead of succeeding as no-ops. Merge checks both events; split checks active memberships; malformed scopes fail nonretryably. Command scopes include an explicit top-level actor and auditable payload fields.
- GREEN: evidence projection only accepts absolute HTTP(S) URLs, includes root-evidence and independence metadata, renders persisted score/model versions, and derives MiniMax degradation from the persisted enrichment origin. Operation details render the escaped, auditable request scope.
- Verification: `uv run pytest tests/events/test_runtime.py tests/web/test_event_queries.py tests/web/test_event_routes.py tests/operations -q` — 49 passed; full suite and Ruff run after the final changes below.

## Final review remediation (RED/GREEN)

- RED: the detail projection derived role data from an ad-hoc raw-item payload and retry allowed terminal failures regardless of durable error reason.
- GREEN: `PublishedEvent` now carries the audited `EvidenceAssessment` snapshot into the immutable event-version payload. The detail query reads role, root key, independence, and limitations from that published snapshot. `test_pipeline_persists_audited_evidence_for_web_detail` drives a real pipeline publication from first-party source metadata through the web query.
- GREEN: durable nonretryable error codes are centrally classified. `OperationCommandService.retry` rejects them and operation detail only renders Retry when the operation's persisted error code is retryable.
- Verification: `uv run pytest tests/events/test_pipeline.py tests/operations/test_commands.py tests/web/test_event_queries.py tests/web/test_operation_queries.py -q` — 11 passed.
