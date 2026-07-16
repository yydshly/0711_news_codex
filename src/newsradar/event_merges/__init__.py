from newsradar.event_merges.facts import (
    EVENT_MERGE_RULE_VERSION,
    load_event_facts,
    merge_input_fingerprint,
)
from newsradar.event_merges.rules import classify_pair
from newsradar.event_merges.schema import (
    EventMergeFacts,
    MergeCandidateDetail,
    MergeCandidateDraft,
    MergeCandidateStatus,
    MergeCandidateType,
)
from newsradar.event_merges.service import EventMergeService, MergeScanResult

__all__ = [
    "EventMergeFacts",
    "EVENT_MERGE_RULE_VERSION",
    "EventMergeService",
    "MergeScanResult",
    "classify_pair",
    "load_event_facts",
    "merge_input_fingerprint",
    "MergeCandidateDetail",
    "MergeCandidateDraft",
    "MergeCandidateStatus",
    "MergeCandidateType",
]
