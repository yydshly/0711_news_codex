# Milestone B canonical identity fix

## Change

- GDELT records now use `Attribution.publisher_url` as `canonical_url` when origin resolution succeeds.
- The GDELT discovery URL remains both `discovery_url` and `original_url`.
- When no publisher URL is resolved, the discovery URL remains canonical and the resolver status is retained.

## Regression coverage

`tests/ingestion/fetchers/test_gdelt.py` parametrizes resolved and unresolved resolver fixtures. It asserts canonical identity, discovery/original URL retention, publisher attribution, and resolution status.

## Verification

- RED: `.venv\\Scripts\\python.exe -m pytest tests/ingestion/fetchers/test_gdelt.py -q` failed for the resolved fixture because canonical URL was `https://gdelt.test/redirect/story` instead of `https://publisher.test/articles/story`.
- GREEN: the same focused test command passed: `6 passed`.
- Focused Ruff: `.venv\\Scripts\\python.exe -m ruff check src/newsradar/ingestion/fetchers/gdelt.py tests/ingestion/fetchers/test_gdelt.py` passed.
- Full Ruff: `.venv\\Scripts\\python.exe -m ruff check .` passed.
- Full pytest: `.venv\\Scripts\\python.exe -m pytest -q` ran with one pre-existing/unrelated failure in `tests/test_migrations.py::test_raw_item_ingestion_upgrade_preserves_0002_history`: it expects the migrated `payload` value to remain the JSON string `'{"legacy": true}'`, but receives `{'legacy': True}`. All other tests completed successfully.
