# Duplicate Manual Target Conclusions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure each unresolved official source identity contributes only one actionable problem while preserving all 187 Target records and all historical evidence.

**Architecture:** `DashboardQueryService` will group current Target records by strictly normalized `official_identity_url`, select one stable managing target for groups without successful FetchRuns, and pass its ID into the existing pure conclusion function. The conclusion function will render duplicate catalog records as deferred without changing YAML, database rows, Worker behavior, or actual-success counts.

**Tech Stack:** Python 3.12, SQLAlchemy 2, FastAPI view models, pytest, Ruff.

## Global Constraints

- Keep exactly 187 Target records; do not delete, archive, merge, or rewrite history.
- Do not modify source YAML availability or ingestion approval.
- Do not perform network requests or read `.env`.
- Do not count duplicate catalog targets as actual success.
- Existing payment, unavailable and approval prohibitions remain visible.
- Existing successful-identity coverage continues to use `covered_by_successful_target`.
- Normalize only scheme/host case, trailing path slash and fragment; retain query.
- Do not use fuzzy names, common Provider ID or common registrable domain to infer duplicates.
- Do not push or merge without user confirmation.

---

### Task 1: Pure Duplicate Conclusion

**Files:**
- Modify: `src/newsradar/web/source_conclusions.py`
- Modify: `tests/web/test_source_conclusions.py`

**Interfaces:**
- Consumes: `SourceConclusionInput.managed_by_target_id: str | None`.
- Produces: `SourceConclusion(code="duplicate_catalog_target", bucket="deferred", ...)`.

- [ ] **Step 1: Write the failing conclusion test**

```python
def test_duplicate_catalog_target_is_deferred_not_success() -> None:
    conclusion = conclude_source(
        SourceConclusionInput(
            "catalog_only",
            "manual_only",
            False,
            None,
            managed_by_target_id="universe-axios-1",
        )
    )
    assert conclusion.code == "duplicate_catalog_target"
    assert conclusion.bucket == "deferred"
    assert conclusion.label == "重复目录项"
    assert "universe-axios-1" in conclusion.reason
```

- [ ] **Step 2: Run the test and verify red**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/web/test_source_conclusions.py::test_duplicate_catalog_target_is_deferred_not_success -x`  
Expected: FAIL because the input has no `managed_by_target_id` field.

- [ ] **Step 3: Implement the minimal pure rule**

Add `managed_by_target_id: str | None = None` to `SourceConclusionInput`. After payment/unavailable/approval and successful-identity coverage checks, but before manual/public-candidate checks, return the Chinese duplicate conclusion when the field is present.

- [ ] **Step 4: Test precedence explicitly**

Add parameterized cases proving `requires_payment`, `unavailable`, `requires_approval`, and `covered_by_successful_target_id` win over `managed_by_target_id`.

- [ ] **Step 5: Run focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/web/test_source_conclusions.py`  
Expected: PASS.

### Task 2: Stable Managing Target Selection

**Files:**
- Modify: `src/newsradar/web/queries.py`
- Modify: `tests/web/test_queries.py`

**Interfaces:**
- Consumes: current `SourceDefinitionRecord` rows, their priority-one public method, and `successful_fetch_ids`.
- Produces: `_managing_target_ids(records, successful_fetch_ids, methods) -> dict[str, str]`, mapping duplicate target ID to managing target ID.

- [ ] **Step 1: Write a failing query test for a primary/search pair**

Create two manual catalog targets with the same official URL, one `publisher_feed` ID ending `-1` and one `search_query` ID ending `-2`. Assert the first remains `manual_only + user_action`, while the second becomes `duplicate_catalog_target + deferred` and names the first.

- [ ] **Step 2: Run the focused test and verify red**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/web/test_queries.py::test_duplicate_manual_identity_has_one_actionable_manager -x`  
Expected: FAIL because both rows currently return `manual_only`.

- [ ] **Step 3: Implement strict identity grouping and stable ranking**

Reuse `_normalized_official_identity`. Group only records with a non-empty normalized identity. Skip groups of one. If any group member has successful FetchRun evidence, do not emit `managed_by_target_id`; the existing successful coverage map remains authoritative. Otherwise rank by:

```python
(
    not has_public_candidate(source_id),
    source.target_type != "publisher_feed",
    not source.id.endswith("-1"),
    source.id,
)
```

The lowest tuple is the manager. Map every other group member to that ID.

- [ ] **Step 4: Add public-candidate and URL-boundary tests**

Prove that a credential-free RSS/Sitemap target wins over a manual HTML target; trailing slashes merge; distinct path and query values remain separate.

- [ ] **Step 5: Add successful coverage regression**

When one group member has `succeeded` FetchRun evidence, the other must retain `covered_by_successful_target`, not `duplicate_catalog_target`.

- [ ] **Step 6: Run query/conclusion regressions**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/web/test_queries.py tests/web/test_source_conclusions.py`  
Expected: PASS.

### Task 3: Real Catalog and Summary Acceptance

**Files:**
- Modify: `tests/web/test_capability_queries.py` only if a read-only catalog assertion is useful.
- Modify: `tests/web/test_routes.py` only if rendered label coverage is absent.

**Interfaces:**
- Consumes: current 187-target YAML catalog synchronized in test fixtures or the existing database.
- Produces: stable summary invariants and rendered Chinese duplicate conclusions.

- [ ] **Step 1: Add a real-catalog assertion for the six duplicate manual groups**

Assert that these secondary IDs resolve to `duplicate_catalog_target`: Axios `-2`, Discord `-2`, Forbes `-2`, Fortune `-2`, Semafor `-2`, Washington Post `-2`. Assert Washington Post `-1` remains `public_candidate_pending_acceptance`.

- [ ] **Step 2: Assert summary invariants**

Assert total remains 187; actual success does not change; all four buckets sum to total; exactly six records move from user action to deferred relative to the pre-change database snapshot.

- [ ] **Step 3: Run focused web tests and Ruff**

Run: `.\.venv\Scripts\python.exe -m pytest -q tests/web`  
Expected: PASS.  
Run: `.\.venv\Scripts\ruff.exe check src/newsradar/web tests/web`  
Expected: `All checks passed!`

- [ ] **Step 4: Commit implementation**

```powershell
git add -- src/newsradar/web/source_conclusions.py src/newsradar/web/queries.py tests/web
git commit -m "fix: collapse duplicate manual target conclusions"
```

### Task 4: Full and Browser Verification

**Files:**
- No production files expected beyond Tasks 1–3.

**Interfaces:**
- Consumes: merged feature behavior and live project database.
- Produces: evidence that UI counts are accurate without data/network mutation.

- [ ] **Step 1: Run full verification**

Run: `.\.venv\Scripts\python.exe -m pytest -q`  
Expected: all tests pass with documented skips.  
Run: `.\.venv\Scripts\ruff.exe check src tests`  
Expected: `All checks passed!`

- [ ] **Step 2: Start a read-only feature Web instance on an unused local port**

Use the main project working directory only to inherit the existing database configuration; run this worktree's `newsradar web`. Do not start a Worker.

- [ ] **Step 3: Verify the live targets page**

Confirm:

- six secondary manual targets display `重复目录项` and name their managing target;
- six managing targets retain their real current conclusion;
- Washington Post primary remains `已有公开路径待验收`;
- actual success remains unchanged;
- total remains 187 and all four buckets sum to 187.

- [ ] **Step 4: Final status check**

Run: `git diff --check` and `git status --short --branch`.  
Expected: clean feature worktree except intentional committed changes; no report or `.env` changes.

