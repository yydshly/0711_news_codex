# RawItem Ingestion v1 Milestone D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit a five-layer 20-target matrix and prove live coverage, failure isolation, worker recovery, security and non-blocking behavior before integration.

**Architecture:** Milestone D adds no new product subsystem. It uses audited YAML, repeatable acceptance commands and evidence reports to verify the already-built adapters and runtime under real network and failure conditions.

**Tech Stack:** Existing CLI, PostgreSQL, pytest, Ruff, PowerShell, browser acceptance tooling.

## Global Constraints

- Milestones A–C must pass before live acceptance.
- Live failures remain failures or external blockers; do not edit assertions or reports to manufacture success.
- Never place credentials in YAML, database dumps, reports, logs or screenshots.
- Do not enable a target until identity, endpoint, terms, fields, freshness and risk are reviewed.

## File Structure

- `reports/raw-item-ingestion-target-matrix.md`: 20-target audited coverage matrix.
- `reports/raw-item-ingestion-live-acceptance.md`: three-round live Probe/Fetch evidence.
- `tests/acceptance/test_worker_recovery.py`: process-loss and lease-recovery proof.
- `tests/acceptance/test_nonblocking_web.py`: Web responsiveness during slow Fetch.
- `reports/raw-item-ingestion-reliability.md`: concurrency, timeout, recovery and redaction evidence.
- `reports/raw-item-ingestion-v1-final.md`: requirement-to-evidence completion report.

---

### Task D1: Final Five-Layer Target Audit

**Files:**
- Modify: audited `providers/*.yaml`
- Modify: audited `sources/**/*.yaml`
- Create: `reports/raw-item-ingestion-target-matrix.md`
- Modify: `tests/ingestion/test_open_source_matrix.py`

**Interfaces:**
- Produces: at least 20 reviewed targets across five layers; at least 15 free usable targets; accurate blocked Reddit/YouTube/restricted-platform entries.
- Consumes: strict YAML and eligibility contracts.

- [ ] Extend the matrix test to require official identity evidence, role, language, topics, approved method, fallback or explicit no-fallback, reviewed date, risk and ingestion decision.
- [ ] Audit at least 4 official/developer, 5 professional-media, 3 aggregator, 4 social/community and 4 research/developer targets; overlap counts only when the matrix explicitly records both roles, while total unique targets remains at least 20.
- [ ] Confirm X, Facebook, Instagram, Threads, TikTok and LinkedIn remain visible with actual unlock requirements and are excluded from successful-fetch counts.
- [ ] Generate the Markdown matrix with exact endpoint, role, availability, credentials, cost, last probe, missing fields, risk and conclusion.
- [ ] Run: `uv run pytest tests/ingestion/test_open_source_matrix.py tests/test_source_universe_catalog.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add providers sources reports/raw-item-ingestion-target-matrix.md tests/ingestion/test_open_source_matrix.py tests/test_source_universe_catalog.py
git commit -m "docs: approve ingestion target matrix"
```

### Task D2: Three-Round Live Probe and Fetch Acceptance

**Files:**
- Create: `reports/raw-item-ingestion-live-acceptance.md`

- [ ] Start the project-local database and apply migrations.
- [ ] Sync Provider/Source catalogs and record definition counts/hashes.
- [ ] Run three content-probe rounds for at least 15 free usable targets; run capability probes for credential/approval/payment-blocked targets, all with timestamps and conservative spacing.
- [ ] Run three approved Fetch rounds for at least 15 free targets; record inserted, updated, unchanged, skipped, failed, ETag/Last-Modified/cursor and duration.
- [ ] Verify at least one 304/conditional no-change path, one aggregator original-URL resolution, one social interaction payload and one credential-blocked adapter.
- [ ] Query PostgreSQL to confirm RawItem uniqueness, snapshot-on-change only, FetchRun counts and duplicate-candidate uniqueness.
- [ ] Write exact commands, timestamps and outcomes into the report. Any target that fails three rounds is not counted as successful.
- [ ] Commit:

```bash
git add reports/raw-item-ingestion-live-acceptance.md
git commit -m "test: record live ingestion acceptance"
```

### Task D3: Reliability, Concurrency, and Security Drills

**Files:**
- Create: `tests/acceptance/test_worker_recovery.py`
- Create: `tests/acceptance/test_nonblocking_web.py`
- Create: `reports/raw-item-ingestion-reliability.md`

- [ ] Write an acceptance test that kills a Worker after a committed item, expires the lease, starts another Worker, and proves the operation finishes without duplicate RawItem or snapshot.

```python
def test_expired_worker_lease_is_recovered_without_duplicate_item(runtime):
    operation_id = runtime.enqueue_fetch("hackernews-top")
    first = runtime.start_worker("worker-a", stop_after_first_commit=True)
    first.wait()
    runtime.clock.advance(seconds=61)
    runtime.start_worker("worker-b").run_until_idle()
    assert runtime.operation(operation_id).status == "succeeded"
    assert runtime.count_raw_items(external_id="42") == 1
    assert runtime.count_snapshots(external_id="42") == 1
```
- [ ] Write a two-Worker lease test proving one Operation and one Source FetchRun are not double-owned.
- [ ] Write a slow-fetch Web test proving operation creation returns immediately and read-only routes respond while the Worker remains busy.
- [ ] Exercise connection/read/source/operation/database-lock timeouts, cancellation and maximum attempts; assert no task remains permanently `running` after lease expiry.
- [ ] Generate a diagnostic bundle during a forced failure and scan it plus rotated logs for seeded secrets.
- [ ] Record durations, worker IDs, attempt IDs, recovery transitions and log correlation in the reliability report.
- [ ] Run: `uv run pytest tests/acceptance tests/operations tests/web/test_security.py -q`.

Expected: PASS.

- [ ] Commit:

```bash
git add tests/acceptance reports/raw-item-ingestion-reliability.md
git commit -m "test: prove ingestion runtime reliability"
```

### Task D4: Final Quality Gate and Handoff

**Files:**
- Modify: `README.md`
- Create: `reports/raw-item-ingestion-v1-final.md`

- [ ] Run `uv run ruff check .`; require exit 0.
- [ ] Run `uv run pytest`; require all tests pass and record exact count/warnings.
- [ ] Run migrations from an existing `0002` database and from an empty database; verify both reach head.
- [ ] Repeat desktop/mobile browser acceptance and capture route/status evidence without secrets.
- [ ] Verify `git diff --check`, clean worktree, no `.env`, `.local`, credentials or generated diagnostics tracked.
- [ ] Write a requirement-by-requirement final report mapping the design completion criteria to commands, test evidence and live evidence. List external blockers separately.
- [ ] Commit:

```bash
git add README.md reports/raw-item-ingestion-v1-final.md
git commit -m "docs: complete raw item ingestion v1 acceptance"
```

After D4, use `superpowers:requesting-code-review`, address findings, rerun the complete gate, and then use `superpowers:finishing-a-development-branch` to present merge/PR options. Do not merge automatically.
