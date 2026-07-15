# Task 5 Report: explainable heat and seven-day trends

## Delivered

- Added deterministic `HeatSnapshot`, `TrendDirection`, and `TrendAssessment` with a
  24-hour baseline selected from persisted snapshots within the preceding seven days.
- Persisted a version-local `heat_breakdown` containing all score dimensions,
  velocity input, independent-root count, accepted engagement fields, and credibility
  reasons.
- Persisted a version-local `trend` with its direction, delta, comparison heat, and
  comparison snapshot timestamp. Historical heat is loaded solely from immutable
  `EventScoreRecord` rows; no reader-facing code recomputes it from wall-clock time.
- Threaded the pipeline's run snapshot time into publishing. Existing evidence gates
  continue to classify community-only high-engagement events as `signal`, never as a
  confirmed hotspot.

## TDD evidence

The initial targeted run failed during collection because `newsradar.events.trends`
did not exist. After implementation:

```text
uv run pytest tests/events/test_trends.py tests/events/test_quality.py tests/events/test_ranking.py tests/events/test_publishing.py -q
38 passed

uv run ruff check <task files>
All checks passed!

uv run pytest -q
exit 0 (with existing third-party deprecation warnings)
```
