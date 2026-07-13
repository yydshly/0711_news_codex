# Final Fix Report

## Scope

- Preserved all YAML files, report baselines, and `.env` files.
- No source-fetch network request was made during this fix.

## Fixes

1. Trial fetcher construction now has an explicit factory allowlist. Only fetchers
   declared credential-free may be constructed with `credential_free_only=True`.
   Credential-reading YouTube and Reddit host routes are blocked before either a
   credential provider or specialized fetcher is constructed, with the stable
   operation error code `eligibility_trial_credentials_not_allowed`.
2. Trial CLI source filtering reads snapshots in one
   `latest_probe_snapshots(selected_ids)` call.
3. Trial eligibility rejects NaN, infinity, and values outside `[0, 1]` with
   `invalid_field_completeness`.
4. Added Worker regressions for YouTube and Reddit special hosts, including
   assertions that credential providers, specialized fetchers, and both GET/POST
   network paths are not reached. Added a non-trial regression ensuring the
   regular specialized YouTube fetcher is still selected.
5. Trial eligibility now rejects case-insensitive `Authorization`,
   `Proxy-Authorization`, `Cookie`, and `Set-Cookie` method headers. Trial
   selection skips a sensitive higher-priority method when a header-safe method
   exists; otherwise it returns `sensitive_headers_not_allowed` before fetcher
   construction or network work. The factory repeats this check as a defense in
   depth boundary.

## Verification

- `uv run --extra dev pytest tests/test_trial_cli.py tests/ingestion/test_trial.py tests/operations/test_fetch_runtime.py -q` — 37 passed.
- `uv run --extra dev pytest tests/ingestion tests/operations tests/test_trial_cli.py tests/web/test_trial_dashboard.py tests/web/test_queries.py -q` — 198 passed (one pre-existing FastAPI/TestClient deprecation warning).
- `uv run --extra dev ruff check src tests` — passed.
- `git diff --check` — passed.
