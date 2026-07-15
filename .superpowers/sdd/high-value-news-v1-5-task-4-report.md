# Task 4 report: evidence roots and confirmation closure

## Delivered

- Kept the existing `EventStatus`, `EvidenceAssessment.root_evidence_key`,
  `decide_publication`, and `decide_event_tier` flow; no parallel signal state
  or evidence-root model was added.
- Evidence roles remain deterministic from the frozen source `nature` and
  `roles` carried into `ClusterItem`. Item/model-supplied `evidence_role` is
  only a conflict signal and cannot override that audited metadata.
- Aggregator redirect URLs and syndicated copies resolve to their upstream
  `original_url` root. Duplicate roots are therefore not independent evidence.
- Community, social, and aggregator records remain early signals. Confirmation
  requires an official root for its own publication or two independent
  professional-media roots; official content that attributes a distinct
  upstream URL is not an independent confirmation.
- `PublicationDecision` now exposes `missing_confirmation`. Immutable event
  version payloads include the already-present `status` plus an
  `evidence_summary` containing official/professional root counts,
  community/social signal count, aggregator pointer count, and missing
  confirmation requirements.

## TDD evidence

1. Added RED tests for aggregator redirect root selection, missing confirmation
   on early signals, event-version evidence summaries, and official-source
   attribution. The first targeted run failed on the intended missing behavior;
   the official attribution test was separately observed failing before its
   minimal implementation.
2. Implemented the smallest deterministic changes and re-ran the target suite.

## Verification

`uv run pytest tests/events/test_evidence.py tests/events/test_scoring.py tests/events/test_pipeline.py -q`

Result: `47 passed`.

## Concerns

- “Own publication” is conservatively identified from an audited distinct
  `original_url`; a source without upstream attribution remains eligible as its
  own first-party publication. Full ownership verification requires additional
  source identity metadata and is intentionally outside this task.

## Review P1 follow-up

- The optional-evidence `decide_publication(candidate)` path now calls the
  same `assess_evidence(candidate.items)` function as normal publication. It
  no longer trusts `ClusterItem.evidence_role` to set either role or
  independence.
- Added a RED regression where an audited aggregator advertises
  `evidence_role=OFFICIAL`; the call returned `CONFIRMED` before the fix and
  returns `EMERGING` after it.
- Re-verified with:
  `uv run pytest tests/events/test_evidence.py tests/events/test_scoring.py tests/events/test_pipeline.py -q`
  (`48 passed`).
