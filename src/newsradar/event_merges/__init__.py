from newsradar.event_merges.facts import (
    EVENT_MERGE_RULE_VERSION,
    load_event_facts,
    merge_input_fingerprint,
)
from newsradar.event_merges.rules import classify_pair
from newsradar.event_merges.schema import (
    EventMergeFacts,
    MergeApplyResult,
    MergeCandidateDetail,
    MergeCandidateDraft,
    MergeCandidateStatus,
    MergeCandidateType,
)
from newsradar.event_merges.service import (
    EventMergeService,
    MergeScanResult,
    candidate_still_safe,
)

__all__ = [
    "EventMergeFacts",
    "MergeApplyResult",
    "EVENT_MERGE_RULE_VERSION",
    "EventMergeService",
    "MergeScanResult",
    "classify_pair",
    "load_event_facts",
    "merge_input_fingerprint",
    "candidate_still_safe",
    "MergeCandidateDetail",
    "MergeCandidateDraft",
    "MergeCandidateStatus",
    "MergeCandidateType",
]
