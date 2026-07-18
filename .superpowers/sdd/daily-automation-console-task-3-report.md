# Task 3 Report — Shared Local Wave Plans and Due Daily Automation Enqueue

## Scope

Implemented the Task 3 durable enqueue boundary only.  This adds no Worker polling loop,
no web automation controls, and no network or MiniMax action during plan construction.

## TDD evidence

### RED

1. `uv run --extra dev pytest tests/daily_reports/test_automation_service.py -q`
   initially failed during collection with
   `ModuleNotFoundError: No module named 'newsradar.daily_reports.automation_service'`.

2. `uv run --extra dev pytest tests/operations/test_commands.py::test_enqueue_daily_autopilot_result_reports_whether_the_run_was_created -q`
   failed with `AttributeError` because `enqueue_daily_autopilot_result` did not exist.

3. `uv run --extra dev pytest tests/operations/test_commands.py::test_enqueue_wave_freezes_plan_atomically tests/operations/test_commands.py::test_enqueue_wave_rejects_invalid_concurrency -q`
   failed because frozen scope lacked the two concurrency values and the new keyword
   arguments were unsupported.

4. `uv run --extra dev pytest tests/waves/test_runtime.py::test_wave_applies_global_and_provider_network_limits tests/waves/test_runtime.py::test_wave_rejects_invalid_persisted_concurrency_before_starting_members -q`
   failed because the runtime still used hard-coded semaphores and accepted invalid scope.

5. `uv run --extra dev pytest tests/daily_reports/test_automation_service.py::test_tick_keeps_the_due_lock_until_enqueue_and_schedule_mark_commit -q`
   failed with three observed commits rather than the required one final commit.  This
   exposed the due-lock transaction boundary issue before the corrective refactor.

### GREEN

- `uv run --extra dev pytest tests/daily_reports/test_automation_service.py -q` — 3 passed.
- `uv run --extra dev pytest tests/operations/test_commands.py::test_enqueue_daily_autopilot_result_reports_whether_the_run_was_created -q` — 1 passed.
- `uv run --extra dev pytest tests/operations/test_commands.py::test_enqueue_wave_freezes_plan_atomically tests/operations/test_commands.py::test_enqueue_wave_rejects_invalid_concurrency -q` — 5 passed.
- `uv run --extra dev pytest tests/waves/test_runtime.py::test_wave_applies_global_and_provider_network_limits tests/waves/test_runtime.py::test_wave_rejects_invalid_persisted_concurrency_before_starting_members -q` — 4 passed.
- Full focused gate:
  `uv run --extra dev pytest tests/daily_reports/test_automation_service.py tests/operations/test_commands.py tests/waves/test_runtime.py tests/web/test_daily_autopilot_pages.py tests/web/test_cli.py -q`
  — 61 passed.  The only output is the pre-existing FastAPI/httpx TestClient deprecation warning.
- Ruff:
  `uv run ruff check src/newsradar/daily_reports/automation_service.py src/newsradar/waves/local_plan.py src/newsradar/web/app.py src/newsradar/cli.py src/newsradar/operations/commands.py src/newsradar/waves/runtime.py tests/daily_reports/test_automation_service.py tests/operations/test_commands.py tests/waves/test_runtime.py tests/web/test_daily_autopilot_pages.py`
  — all checks passed.
- `git diff --check` — passed.

## Design decisions

- `build_local_wave_plan` is the single local construction boundary.  It reads reviewed
  profile, provider, and source YAML; synchronizes reviewed records; obtains persisted
  probe/fetch evidence and configured credential names; and builds the existing `WavePlan`.
  It flushes rather than commits, so callers that own a transaction retain their lock.
- `DailyAutomationService.tick()` receives a plan factory for deterministic tests and uses
  the shared factory in production with a fixed 24-hour window.  For due work it holds one
  transaction from `lock_due` through enqueue/reuse, `mark_scheduled`, and its final commit.
- `DailyAutopilotEnqueueResult` separates `run_id` from whether a run was created.  The
  old `enqueue_daily_autopilot() -> int` remains a wrapper with its original committing
  behavior.  The result method additionally supports the explicit service-owned
  transaction path.
- High-value wave operations now freeze `global_concurrency=8` and
  `provider_concurrency=2`.  The runtime honors valid persisted values, uses compatible
  defaults for historical scopes, and rejects invalid persisted limits before member work.

## Files changed

- Created `src/newsradar/waves/local_plan.py`.
- Created `src/newsradar/daily_reports/automation_service.py`.
- Created `tests/daily_reports/test_automation_service.py`.
- Updated the requested CLI, Web, command, runtime, and focused test files.

## Self-review

- Confirmed shared construction has no HTTP-client or MiniMax invocation.
- Confirmed Web and CLI call the shared factory and preserve profile-specific CLI windows.
- Confirmed automatic scheduling is not enabled by this change; the existing repository
  default remains disabled.
- Confirmed daily tick enqueues only durable work and performs no Worker execution.
- Confirmed scope validation and executor concurrency tests cover global and provider limits.
- Reviewed the final diff and ran `git diff --check`; no whitespace errors.

## Concerns

No unresolved implementation concerns.  The focused gate carries an existing third-party
FastAPI/httpx deprecation warning; it is unrelated to this task and does not fail the gate.

## Review-fix follow-up

### Additional RED evidence

- The rollback regression left `db_session.in_transaction()` true after a plan-factory
  exception.
- The public result enqueue signature exposed `in_transaction`.
- `True` was accepted as a high-value global concurrency value and string inputs raised
  `TypeError` rather than the required `ValueError`.
- The restored `/events/update` regression test could not patch `load_wave_profile`, showing
  the manual route no longer consulted the default profile window.

### Fixes and GREEN evidence

- Public `enqueue_daily_autopilot_result()` is again durable-only.  The service uses a
  private transaction-owned helper, and fresh-session tests prove both the public result
  path and legacy integer wrapper persist their run before reopening the session.
- `DailyAutomationService.tick()` now rolls back on any exception from its due transaction;
  the plan-factory failure regression confirms the reusable session is left without an open
  transaction or a partial autopilot run.
- Enqueue validation now rejects bool and non-integer concurrency inputs with the same error
  contract and limits as the runtime.
- `/events/update` loads the profile window rather than forcing 24; scheduled ticks remain
  the only caller that explicitly supplies 24 hours.
- `uv run --extra dev pytest tests/daily_reports/test_automation_service.py tests/operations/test_commands.py tests/waves/test_runtime.py tests/web/test_daily_autopilot_pages.py tests/web/test_cli.py tests/web/test_high_value_wave_pages.py -q`
  — 73 passed, with only the existing FastAPI/httpx deprecation warning.
- Targeted Ruff checks and `git diff --check` passed.
