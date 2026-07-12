# RawItem Ingestion v1.1 Closure Design

## 1. Goal

RawItem Ingestion v1.1 closes the operational and documentation gaps found by the post-merge audit of v1. It does not add event clustering, MiniMax news synthesis, scheduling, recommendations, daily reports, or notifications.

The release is complete only when Web and CLI use the same durable operation path, the recommended local runtime starts both Web and Worker, credential-gated adapters can be unlocked through the ignored `.env`, planned Web review actions exist, runtime deadlines and failure health are accurate, and documentation matches actual behavior.

## 2. Constraints

- Develop only on `feature/raw-item-v1-1-closure` in its isolated worktree.
- Preserve YAML as the audited source truth and PostgreSQL as runtime state.
- No browser-login scraping, cookies, CAPTCHA bypass, arbitrary URLs, article HTML, Docker, Redis, or Celery.
- Secrets never enter YAML, database payloads, logs, diagnostics, templates, reports, or command output.
- All Web writes remain loopback-only POST actions protected by Host/Origin checks, SameSite Strict session cookies, CSRF/action tokens, registered IDs, and idempotency.
- Social and aggregator content remains discovery/engagement, never independent factual evidence.
- MiniMax remains optional and is not added to the ingestion or Web flow in v1.1.

## 3. Runtime Supervisor

`newsradar serve` becomes the recommended local runtime. It starts two independently observable child processes:

1. `newsradar web`, bound to `127.0.0.1:8765`.
2. `newsradar worker --forever`, with a stable local worker ID.

The supervisor forwards Ctrl+C and termination, stops the sibling if either process exits unexpectedly, returns a non-zero status for abnormal child failure, and emits only scrubbed lifecycle messages. It does not silently restart a crashing child in v1.1.

`newsradar web`, `newsradar worker --once`, and `newsradar worker --forever` remain available for diagnosis and split deployment. `worker` should default to `--forever`; `--once` remains explicit for tests and maintenance.

## 4. Unified Operation Execution

Web and CLI submit the same typed `OperationRun` request. Network work occurs only in Worker handlers.

`newsradar fetch [SOURCE_ID]` will:

1. Validate source/provider IDs and eligibility inputs.
2. Enqueue a Fetch operation.
3. By default wait for a terminal state and print the persisted result.
4. Support `--no-wait` to return after enqueue.

The command no longer performs HTTP itself. Every execution creates an `OperationAttempt`, events, timestamps, result summary, and linked `FetchRun`. Cancellation, retry classification, lease renewal, and recovery therefore behave identically for Web and CLI.

## 5. Credential Configuration

`Settings` gains secret-backed fields for:

- `GITHUB_TOKEN`
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `YOUTUBE_API_KEY`

One credential provider reads resolved Settings rather than calling `os.environ` directly. It exposes values only to the request adapter that needs them.

Access methods gain a backward-compatible `auth_envs` list. Existing scalar `auth_env` remains readable during migration, but canonical YAML uses `auth_envs`. Eligibility requires all declared variables and reports only missing variable names, never values.

The audited catalog adds:

- OAuth REST methods for the three reviewed Reddit communities.
- At least one reviewed YouTube Data API channel or search target.

These targets stay disabled by default. With missing credentials they deterministically return `missing_credentials`; with credentials they use only official APIs and remain subject to approval/quota policy.

## 6. Web Actions

The existing A-style pages add:

- `POST /operations/{id}/cancel`
- `POST /operations/{id}/retry`
- `POST /duplicates/{id}/confirm`
- `POST /duplicates/{id}/dismiss`

Cancel and retry use OperationRepository semantics and preserve prior attempts. Retry creates a new OperationRun with `requested_scope.retry_of_operation_id` pointing to the original operation rather than rewriting its history; queries expose this relationship without adding a nullable database foreign key in v1.1.

Duplicate review changes only the candidate status and review metadata. It never merges or deletes RawItems automatically.

Action-token storage supports multiple outstanding tokens so separate browser tabs do not invalidate one another. Tokens remain one-time and bounded.

## 7. Deadlines, Pagination, and Cancellation

The enforced defaults are:

- Connect timeout: 10 seconds.
- Read timeout: 30 seconds.
- HTTP request ceiling: 45 seconds.
- Source execution ceiling: 2 minutes.
- Operation ceiling: 30 minutes.
- Database lock wait: 5 seconds.
- Worker lease: 60 seconds, renewed every 15 seconds.
- Default pages per source run: 1; configurable up to 10.

The operation deadline is persisted or deterministically derived from start time so retries cannot reset it indefinitely. Source timeout wraps adapter execution. Pagination observes maximum items, maximum pages, cursor origin constraints, response-size limits, and cancellation at request/page/source boundaries.

Cancellation does not kill an open database transaction. It becomes effective at the next safe boundary.

## 8. Source Health

Failure completion updates `SourceFetchStateRecord`:

- increments `consecutive_failures`;
- records `last_failure_at`;
- records a scrubbed `last_error_code`.

Success resets the failure streak and updates `last_success_at`. Missing credentials and policy blocks are visible but do not masquerade as transport instability.

Runtime observations never rewrite YAML automatically.

GDELT remains cataloged and probeable but changes to `status: degraded` with default ingestion disabled. Operators may run an explicit one-off dry run or re-enable it after evidence review.

## 9. PostgreSQL Recovery

Initialization records which resources it created during the current attempt. If configure/start/create-database/write-env fails, it stops only the process started by that attempt, removes temporary secret files, preserves data and logs, and prints a precise recovery path.

`newsradar db repair` handles recognized partial states, including initialized data with a missing connection setting. It never deletes `.local/postgres`; destructive recovery remains a documented manual action.

## 10. Protocol and Performance Corrections

- Parse `Retry-After` as either delta seconds or HTTP-date and cap it by policy.
- Narrow duplicate-candidate lookup by time window, title fingerprint/similarity prefilter, and cross-source constraints instead of scanning every RawItem.
- Preserve identical normalization and candidate decisions for existing fixtures.
- Add indexes only through an additive Alembic migration when query evidence requires them.

## 11. Documentation and UI Truthfulness

README and navigation distinguish read-only browsing from explicit write actions. They document:

- `newsradar serve` as the recommended start command;
- split Web/Worker commands;
- Worker-offline queue behavior;
- CLI wait/no-wait behavior;
- cancellation and retry;
- credential creation boundary and missing-credential behavior;
- GDELT degraded status;
- MiniMax as an adapter that is not yet wired to event/news production.

No page may label the whole application as read-only while offering write actions.

## 12. Data Flow

```text
Web POST / CLI command
        |
        v
typed validation + eligibility
        |
        v
PostgreSQL OperationRun (queued)
        |
        v
Worker lease + Attempt + heartbeat
        |
        v
IngestionService deadline/pagination
        |
        v
FetchRun + RawItem + Snapshot + Audit
        |
        v
terminal Operation result shown by Web/CLI
```

## 13. Error Handling

- Validation, credential, approval, policy, ordinary 4xx, parsing, schema, and identity conflicts are terminal unless an explicit operator retry creates a new operation.
- Connect/read transport failures, 408, 425, 429, and 5xx use bounded exponential backoff with jitter and valid Retry-After handling.
- Source timeout becomes `limit_exceeded/source_timeout`; operation timeout becomes terminal `limit_exceeded/operation_timeout`.
- One source failure does not abort a multi-source operation; the operation may finish `partial`.
- All errors use existing redaction and correlation identifiers.

## 14. Verification

Required automated evidence:

- Supervisor startup, child failure, Ctrl+C, and shutdown tests.
- CLI and Web enqueue the same request and produce equivalent Attempt/Event/FetchRun records.
- `.env` credentials unlock fixture adapters without secret leakage.
- Missing/partial Reddit credentials and missing YouTube key remain blocked.
- Cancel/retry and duplicate confirm/dismiss CSRF/idempotency tests.
- Source and Operation timeout tests with no permanent `running` state.
- Failure streak increment/reset tests.
- Retry-After delta/date tests.
- Multi-tab action token test.
- PostgreSQL init partial-failure and repair tests.
- Duplicate-candidate bounded-query regression and scale test.
- GDELT excluded from default approved fetch.

Final gates:

1. Configure the ignored worktree `.env` for the project-local PostgreSQL instance.
2. Apply migrations and sync catalogs.
3. Run the real PostgreSQL contention test without skips.
4. Run complete pytest with zero skips, Ruff, and `git diff --check`.
5. Verify Web-only, Worker-only, and Supervisor modes in a browser and terminal.
6. Run secret scans and create a scrubbed diagnostic bundle.
7. Request an independent `5.6 Sol + high reasoning` final review before merge.

## 15. Implementation Batches

1. Runtime Supervisor and unified Operation path.
2. Settings credentials and audited Reddit/YouTube targets.
3. Web cancel/retry and duplicate review.
4. Deadlines, source health, Retry-After, and duplicate-query bounds.
5. PostgreSQL repair, documentation, and browser acceptance.
6. Full gate and independent final review.

Each batch follows red-green TDD, ends in a focused commit, and must not proceed with unresolved Critical or Important review findings.
