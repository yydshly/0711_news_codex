# Task 1 Implementation Report

## Status

DONE

## Modified files

- `src/newsradar/events/entities.py`
- `src/newsradar/events/versions.py`
- `tests/events/test_entities.py`
- `tests/events/test_pipeline.py`

The required implementation commit contains only these four files. This report replaces the pre-existing Task 1 report artifact separately.

## RED evidence

Command:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/events/test_entities.py tests/events/test_pipeline.py::test_pipeline_exposes_current_rule_versions
```

Result: exit code 1 with 6 expected failures. The failures showed:

- `ENTITY_RULE_VERSION` was still `entities-v2` rather than `entities-v3`.
- `item_kind="OpenAI"`, `publisher_name="OpenAI"`, and `source_topics=("OpenAI",)` each still produced `organization:openai`.
- Google source metadata still produced `organization:google` for an unrelated news claim.
- The pipeline algorithm map still exposed `entities-v2`.

This was the expected behavioral failure, not a collection or syntax error.

## GREEN evidence

Focused command:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/events/test_entities.py tests/events/test_pipeline.py::test_pipeline_exposes_current_rule_versions
```

Result: exit code 0, 25 passed.

Required regression command:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
..\..\.venv\Scripts\python.exe -m pytest -q tests/events/test_entities.py tests/events/test_pipeline.py tests/events/test_operation_snapshots.py tests/waves/test_runtime.py tests/web/test_event_queries.py tests/web/test_capability_queries.py
```

Result: exit code 0, 103 passed. Historical snapshot behavior remained covered by the selected regression suite.

## Ruff and diff check

Command:

```powershell
..\..\.venv\Scripts\python.exe -m ruff check src/newsradar/events/entities.py src/newsradar/events/versions.py tests/events/test_entities.py tests/events/test_pipeline.py
```

Result: exit code 0, `All checks passed!`.

Command:

```powershell
git diff --check
```

Result: exit code 0 with no whitespace errors.

## Commit

- `50092212821c03d201d50c40e050c263dcbc2a31` (`fix: isolate event entities from source metadata`)

## Self-review

- The entity extractor now reads only `title`, `summary`, and `content`.
- `RawItemText.item_kind`, `publisher_name`, and `source_topics` remain intact for other consumers.
- Both current-version declarations use the exact immutable version `entities-v3`.
- Tests cover all three excluded metadata channels, all three retained claim-text channels, and the Google News contamination regression.
- Product changes are limited to the four files named by the brief.
- No `.env` file, real database, main-workspace `reports/`, network, push, or merge operation was used.

## Concerns

None.
