from __future__ import annotations

from sqlalchemy.orm import Session

from newsradar.db.models import (
    OperationRunRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceProbeRunRecord,
)


def is_valid_remediation_content_link(
    session: Session, *, source_id: str, content_probe_id: int
) -> bool:
    """Verify the complete immutable remediation evidence chain for a trial fetch."""
    content = session.get(SourceProbeRunRecord, content_probe_id)
    if (
        content is None
        or content.source_id != source_id
        or content.outcome != "success"
        or content.remediation_acquisition_probe_id is None
    ):
        return False
    acquisition = session.get(
        SourceAcquisitionProbeRunRecord, content.remediation_acquisition_probe_id
    )
    if (
        acquisition is None
        or acquisition.outcome != "succeeded"
        or acquisition.operation_run_id is None
        or acquisition.original_probe_id is None
    ):
        return False
    candidate = session.get(SourceAcquisitionCandidateRecord, acquisition.candidate_id)
    operation = session.get(OperationRunRecord, acquisition.operation_run_id)
    if candidate is None or candidate.source_id != source_id or operation is None:
        return False
    scope = operation.requested_scope if isinstance(operation.requested_scope, dict) else {}
    return (
        operation.operation_type == "source_remediation"
        and operation.status == "succeeded"
        and scope.get("source_id") == source_id
        and scope.get("candidate_key") == candidate.candidate_key
        and scope.get("original_probe_id") == acquisition.original_probe_id
    )
