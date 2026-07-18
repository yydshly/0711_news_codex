# Daily report review specificity repair

## Goal

Restore event-specific Chinese audit advice and evidence assessments in newly generated daily reports. The repair must retain deterministic editorial decisions and must not trigger fetching, audio generation, or scheduled work.

## Problem

The current Chinese enrichment stage asks MiniMax only for a title and summary. `build_decision_review` then assigns one of two fixed review/assessment pairs: confirmed or two independent roots receives a keep message; every other event receives the same needs-evidence message. This makes many unrelated events appear identical.

## Design

1. Keep the existing deterministic decision rule (`keep` versus `needs_evidence`). The model must not decide inclusion, evidence strength, or source legality.
2. Build a bounded, URL-free fact card from the existing immutable event snapshot: status, independent-root count, source roles, confirmation summary, limitations, and available publisher names.
3. Extend the Chinese-copy stage to produce only explanatory Chinese text for the already determined decision: a review recommendation and an evidence assessment. Its prompt must state that the decision is fixed and must not be changed.
4. If the model is unavailable or returns invalid text, derive different rule-based explanations from the same fact card. The fallback must name the actual missing evidence category where present, rather than using one universal sentence.
5. Persist the resulting copy in the current editorial-review records and preserve the existing audit fields that distinguish model output from rule fallback.

## Acceptance criteria

- The decision remains exactly the result of the existing deterministic rule.
- A low-evidence batch with distinct limitations or confirmation states produces distinct Chinese recommendations and assessments.
- No prompt accepts URLs, tokens, credentials, or arbitrary untrusted instructions.
- Existing report generation, audio, and source-fetch behaviour remain unchanged.
- Tests cover model output, rule fallback, deterministic decisions, and the prior uniform-template regression.

