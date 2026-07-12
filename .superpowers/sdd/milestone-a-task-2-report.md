# Milestone A Task 2 Report

## Outcome

Implemented backward-compatible ingestion YAML configuration, a side-effect-free fetch
eligibility decision, and deterministic local normalization helpers.

## RED evidence

1. Added the legacy-default and strict-ingestion-field tests in `tests/test_source_schema.py`.
2. Added eligibility matrix and normalization tests in `tests/ingestion/`.
3. Ran:

   ```powershell
   uv run pytest tests/test_source_schema.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py -q
   ```

   The initial run failed at collection exactly because
   `newsradar.ingestion.eligibility` and `newsradar.ingestion.normalization` did not yet
   exist. After the implementation was added, the hash expectation and seven-day
   title-similarity test exposed and corrected the intended normalization semantics.

## GREEN evidence

Focused verification:

```powershell
uv run pytest tests/test_source_schema.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py -q
uv run ruff check src/newsradar/sources/schema.py src/newsradar/ingestion/eligibility.py src/newsradar/ingestion/normalization.py tests/test_source_schema.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py
```

Result: `29 passed`; Ruff reported `All checks passed!`.

Required full-suite verification, run once before commit:

```powershell
uv run pytest
uv run ruff check .
```

Result: `173 passed, 4 warnings in 9.23s`; Ruff reported `All checks passed!`.
The four warnings are pre-existing dependency/configuration deprecation warnings from
Starlette TestClient and Alembic.

## Changed files

- `src/newsradar/sources/schema.py`
- `src/newsradar/ingestion/eligibility.py`
- `src/newsradar/ingestion/normalization.py`
- `tests/test_source_schema.py`
- `tests/ingestion/test_eligibility.py`
- `tests/ingestion/test_normalization.py`
- `.superpowers/sdd/milestone-a-task-2-report.md`

## Self-review

- `IngestionConfig` is frozen, rejects unknown fields, defaults disabled, and is attached via
  `default_factory`, preserving legacy YAML compatibility.
- Eligibility reads only function arguments and immutable validated source state. It does not
  inspect the process environment, alter YAML, use a database, or make a network request.
- It uses the existing `Availability`, `CoverageMode`, `AccessKind`, and `SourceStatus` enums.
  It treats `auth_env` as a configured-name check only and selects the lowest-priority viable
  non-HTML method.
- Normalization uses only standard-library parsing and transformations. URL identity drops
  fragments, default ports, and known tracking parameters while preserving business query
  parameters; hashes use sorted JSON and SHA-256 and exclude engagement/raw payload data.
- `git diff --check` completed without whitespace errors.

## Concerns

None for Task 2. The full suite passes; its four deprecation warnings were not introduced by
this task.

## Review follow-up

### Root cause and RED evidence

Review identified three gaps in the original policy implementation:

1. The method filter excluded only `AccessKind.HTML`, so a non-HTML method marked
   `requires_manual_approval=True` could be selected automatically.
2. `Availability.REQUIRES_CREDENTIALS` passed through the generic method-selection rule,
   which treated an undeclared `auth_env` as sufficient.
3. `content_hash()` serialized aware datetimes using their original offsets, producing
   different hashes for equal instants.

Added regression tests for manual `rest_api` and `public_api` methods, credential-required
sources with and without a configured declared credential, and equal UTC/UTC-07:00 instants.
Before the fix, the five targeted assertions failed: the two manual methods and the
undeclared-credential method were allowed, and equal instants hashed differently.

### Fix and verification

- Automatic selection now excludes every manually approved method. When no automatic method
  remains because approval is required, it returns
  `manual_approval_required` with a stable Chinese reason.
- Credential-required sources now select only an automatic method with a declared `auth_env`
  whose name is present in `configured_env`; otherwise they return `missing_credentials`.
- Aware timestamps are converted to UTC before ISO serialization for content hashing. Naive
  timestamp behavior remains unchanged.

Focused verification:

```powershell
uv run pytest tests/test_source_schema.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py -q
uv run ruff check src/newsradar/ingestion/eligibility.py src/newsradar/ingestion/normalization.py tests/ingestion/test_eligibility.py tests/ingestion/test_normalization.py
```

Result: `34 passed`; Ruff reported `All checks passed!`.

Full-suite verification, run once before this follow-up commit:

```powershell
uv run pytest
uv run ruff check .
```

Result: `178 passed, 4 warnings in 8.15s`; Ruff reported `All checks passed!`. The warnings
remain the existing Starlette TestClient and Alembic deprecations.

### Follow-up self-review and concerns

The changes are scoped to the review findings and keep eligibility pure: only the supplied
credential names are examined, with no process-environment access. No concerns beyond the
existing external deprecation warnings.
