# Milestone B Task 1 Report

## Scope

- Added immutable `Attribution` and `OriginResolutionStatus` contracts.
- Added pure evidence-role filtering: aggregator, social, and community sources cannot independently yield `evidence`.
- Extended normalized raw items and repository persistence for attribution, item-kind, and social identity fields.
- Preserved existing content-hash, snapshot, and idempotency behavior.

## Test evidence

- `uv run pytest tests/ingestion/test_attribution.py tests/ingestion/test_repository.py -q` — 20 passed.
- `uv run ruff check src/newsradar/ingestion/attribution.py src/newsradar/ingestion/schema.py src/newsradar/ingestion/repository.py tests/ingestion/test_attribution.py` — passed.
- `uv run pytest -q` — passed (existing third-party deprecation warnings only).
- `uv run ruff check .` — passed.

## Constraints observed

- No network access or model calls were added.
- The pre-existing unstaged `tests/ingestion/test_normalization.py` formatting change was not modified or staged.
