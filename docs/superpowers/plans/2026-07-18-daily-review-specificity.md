# Daily Review Specificity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore event-specific Chinese review recommendations and evidence assessments without changing deterministic editorial decisions.

**Architecture:** The existing daily Chinese enrichment result will carry explanatory copy in addition to title and summary. The decision is computed before the prompt and persisted unchanged; the prompt receives only a URL-free fact card. A deterministic fact-card fallback preserves specificity when the model is unavailable.

**Tech Stack:** Python 3.12, Pydantic, httpx, SQLAlchemy, pytest, Ruff.

## Global Constraints

- Do not alter fetch, audio, scheduler, or source-availability code.
- The model must not decide inclusion, confirmation, legality, or evidence strength.
- Prompt context must remain URL-free, bounded, and secret-free.
- Each candidate failure must remain isolated from the batch.

---

### Task 1: Add a regression test for event-specific explanatory copy

**Files:**
- Modify: `tests/daily_reports/test_chinese_enrichment.py`
- Modify: `src/newsradar/daily_reports/chinese_enrichment.py`

**Interfaces:**
- Consumes: `DailyReportChineseEnricher.enrich_batch(candidates)`.
- Produces: `DailyReportChineseCopy.review_recommendation` and `DailyReportChineseCopy.evidence_assessment`.

- [ ] **Step 1: Write the failing test**

Add two low-evidence candidates with distinct `confirmation_summary` and `limitations`; configure no API key. Assert their decisions are not tested here, but their fallback `review_recommendation` and `evidence_assessment` are non-empty and differ.

```python
assert first.copy.review_recommendation != second.copy.review_recommendation
assert first.copy.evidence_assessment != second.copy.evidence_assessment
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/daily_reports/test_chinese_enrichment.py::test_rule_fallback_explains_distinct_evidence_gaps -q`

Expected: FAIL because `DailyReportChineseCopy` has no explanatory fields.

- [ ] **Step 3: Write minimal implementation**

Extend `_ChineseResponse` and `DailyReportChineseCopy` with the two explanatory strings. Add `_rule_explanations(snapshot)` which selects a factual Chinese message using status, root count, confirmation summary, and limitations; never use a URL or a source credential. Validate model explanations with the same non-empty simplified-Chinese checks as other copy. Pass existing snapshot copy plus fallback explanations through every error path.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/daily_reports/test_chinese_enrichment.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/daily_reports/test_chinese_enrichment.py src/newsradar/daily_reports/chinese_enrichment.py
git commit -m "fix: make daily review fallbacks evidence-specific"
```

### Task 2: Persist explanatory copy while retaining deterministic decisions

**Files:**
- Modify: `src/newsradar/daily_reports/autopilot.py`
- Modify: `src/newsradar/daily_reports/autopilot_runtime.py`
- Modify: `tests/daily_reports/test_autopilot_runtime.py`

**Interfaces:**
- Consumes: `DailyReportChineseResult.copy` and the existing `_review_values(snapshot)` decision.
- Produces: `DailyReportEditorialReviewDraft` and `DailyReportOverviewEditorialReviewDraft` with specific explanatory text.

- [ ] **Step 1: Write the failing test**

Create two snapshots that both resolve to `needs_evidence` but have different limitations. Pass explicit explanatory copy into `build_decision_review`. Assert both decisions remain `needs_evidence` and their persisted-draft recommendation and assessment differ.

```python
assert left.decision == right.decision == "needs_evidence"
assert left.review_recommendation != right.review_recommendation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py -q`

Expected: FAIL because `build_decision_review` does not accept explanatory copy.

- [ ] **Step 3: Write minimal implementation**

Add optional `review_recommendation` and `evidence_assessment` parameters to the two review builders. Preserve `_review_values` as the exclusive source of `decision`; use the optional explanatory copy only for display text. Pass the enrichment copy from `_write_reviews` to both decision and overview builders.

- [ ] **Step 4: Run tests to verify deterministic behaviour**

Run: `uv run --extra dev pytest tests/daily_reports/test_autopilot_runtime.py tests/daily_reports/test_autopilot.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newsradar/daily_reports/autopilot.py src/newsradar/daily_reports/autopilot_runtime.py tests/daily_reports/test_autopilot_runtime.py
git commit -m "fix: persist specific daily review explanations"
```

### Task 3: Verify the page receives distinct stored review text

**Files:**
- Modify: `tests/web/test_daily_report_pages.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: persisted editorial review records through the existing daily-report page query.
- Produces: a rendered decision brief showing item-specific Chinese advice and evidence assessment.

- [ ] **Step 1: Write the failing page test**

Seed two `needs_evidence` review records with different specific Chinese explanations. Assert the report detail response includes both explanations and the existing Chinese headings.

- [ ] **Step 2: Run test to verify it fails if persistence is incomplete**

Run: `uv run --extra dev pytest tests/web/test_daily_report_pages.py -q`

Expected: PASS after Task 2; if it fails, use its assertion to identify the missing persistence or query boundary.

- [ ] **Step 3: Add concise operator documentation**

State that report conclusions remain rule-based and that Chinese review explanations identify existing evidence and next verification action; model failure falls back to fact-specific Chinese rules.

- [ ] **Step 4: Run targeted and full verification**

Run:

```bash
uv run --extra dev --extra research pytest -q
uv run --extra dev ruff check .
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/web/test_daily_report_pages.py README.md
git commit -m "test: cover specific daily review rendering"
```
