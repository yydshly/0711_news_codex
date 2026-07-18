from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps
from time import monotonic, sleep
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from newsradar.db.models import (
    DailyReportRecord,
    OperationRunRecord,
    SourceRemediationBatchRecord,
    SourceRemediationMemberRecord,
)
from newsradar.event_merges.facts import EVENT_MERGE_RULE_VERSION
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.operations.repository import OperationRepository
from newsradar.operations.retry_policy import is_retryable_error
from newsradar.operations.schema import OperationStatus, OperationType
from newsradar.remediation.evidence_links import is_valid_remediation_content_link
from newsradar.settings import Settings, get_settings
from newsradar.sources.catalog_refresh import CatalogRefreshPlan
from newsradar.sources.catalog_refresh_repository import CatalogRefreshRepository
from newsradar.waves.planning import WavePlan
from newsradar.waves.repository import WaveRepository

if TYPE_CHECKING:
    from newsradar.daily_reports.autopilot import DailyAutopilotStage


class OperationCommandService:
    """Shared Web and CLI command boundary for durable operations."""

    def __init__(
        self,
        session: Session,
        *,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self._sleeper = sleeper
        self._clock = clock
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._settings = settings or get_settings()

    def enqueue_fetch(
        self,
        *,
        source_id: str,
        provider: str | None = None,
        dry_run: bool = False,
        max_items: int | None = None,
        one_off: bool = False,
        trial: bool = False,
        remediation_content_probe_id: int | None = None,
        trigger: str,
    ) -> int:
        if remediation_content_probe_id is not None:
            if not trial:
                raise ValueError("remediation_content_link_requires_trial")
            if not is_valid_remediation_content_link(
                self.session,
                source_id=source_id,
                content_probe_id=remediation_content_probe_id,
            ):
                raise ValueError("invalid_remediation_content_link")
        deadline_at = self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        record = OperationRepository(self.session).enqueue(
            OperationType.FETCH,
            {
                "source_id": source_id,
                "provider": provider,
                "dry_run": dry_run,
                "max_items": max_items,
                "one_off": one_off,
                "trial": trial,
                **(
                    {"remediation_content_probe_id": remediation_content_probe_id}
                    if remediation_content_probe_id is not None
                    else {}
                ),
                "deadline_at": deadline_at.isoformat(),
            },
            trigger=trigger,
        )
        self.session.commit()
        return record.id

    def enqueue_daily_report_audio(
        self, *, report_id: int, rendition: str, trigger: str
    ) -> int:
        self._validate_daily_report_audio_request(report_id, rendition)
        if self.session.in_transaction():
            self.session.commit()
        with self.session.begin():
            return self._enqueue_daily_report_audio(
                report_id=report_id,
                rendition=rendition,
                trigger=trigger,
            )

    def archive_and_enqueue_daily_report_audio(self, *, report_id: int, trigger: str) -> int:
        # Keep the daily-report package out of this module's import path. The
        # CLI remains usable in minimal installations without optional web
        # and research dependencies.
        from newsradar.daily_reports.repository import DailyReportRepository

        if isinstance(report_id, bool) or not isinstance(report_id, int) or report_id <= 0:
            raise ValueError("invalid_daily_report_audio_report_id")
        if self.session.in_transaction():
            self.session.commit()
        with self.session.begin():
            DailyReportRepository(self.session, utcnow=self._utcnow).archive(
                report_id, commit=False
            )
            return self._enqueue_daily_report_audio(
                report_id=report_id,
                rendition="decision",
                trigger=trigger,
            )

    def archive_and_enqueue_daily_report_audios(
        self, *, report_id: int, trigger: str
    ) -> tuple[int, int]:
        """Publish a complete decision/overview audio package in one transaction."""
        from newsradar.daily_reports.repository import DailyReportRepository

        if isinstance(report_id, bool) or not isinstance(report_id, int) or report_id <= 0:
            raise ValueError("invalid_daily_report_audio_report_id")
        if self.session.in_transaction():
            self.session.commit()
        with self.session.begin():
            report = self.session.scalar(
                select(DailyReportRecord)
                .where(DailyReportRecord.id == report_id)
                .with_for_update()
            )
            if report is None:
                raise LookupError("daily_report_not_found")
            if report.status == "archived":
                existing = (
                    self._daily_report_audio_operation_id(report_id, "decision"),
                    self._daily_report_audio_operation_id(report_id, "overview"),
                )
                if all(operation_id is not None for operation_id in existing):
                    return int(existing[0]), int(existing[1])
                raise ValueError("daily_report_audio_package_incomplete")
            reports = DailyReportRepository(self.session, utcnow=self._utcnow)
            reports.assert_audio_package_ready(report_id)
            reports.archive(report_id, commit=False)
            decision_id = self._enqueue_daily_report_audio(
                report_id=report_id,
                rendition="decision",
                trigger=trigger,
            )
            overview_id = self._enqueue_daily_report_audio(
                report_id=report_id,
                rendition="overview",
                trigger=trigger,
            )
            return decision_id, overview_id

    def _daily_report_audio_operation_id(
        self, report_id: int, rendition: str
    ) -> int | None:
        for record in self.session.scalars(
            select(OperationRunRecord)
            .where(
                OperationRunRecord.operation_type
                == OperationType.DAILY_REPORT_AUDIO.value
            )
            .order_by(OperationRunRecord.id.desc())
        ):
            scope = record.requested_scope
            if (
                isinstance(scope, dict)
                and scope.get("daily_report_id") == report_id
                and scope.get("rendition") == rendition
            ):
                return record.id
        return None

    def _enqueue_daily_report_audio(
        self, *, report_id: int, rendition: str, trigger: str
    ) -> int:
        report = self.session.scalar(
            select(DailyReportRecord)
            .where(DailyReportRecord.id == report_id)
            .with_for_update()
        )
        if report is None:
            raise ValueError("daily_report_not_found")
        if report.status != "archived":
            raise ValueError("daily_report_must_be_archived_for_audio")
        if rendition == "overview":
            from newsradar.daily_reports.repository import DailyReportRepository

            readiness = DailyReportRepository(self.session).overview_audio_readiness(
                report_id
            )
            if (
                readiness.total_count == 0
                or readiness.reviewed_count != readiness.total_count
            ):
                raise ValueError("daily_report_overview_review_incomplete")
            if readiness.included_count == 0:
                raise ValueError("daily_report_overview_has_no_included_items")
        active = next(
            (
                record
                for record in self.session.scalars(
                    select(OperationRunRecord)
                    .where(
                        OperationRunRecord.operation_type
                        == OperationType.DAILY_REPORT_AUDIO.value,
                        OperationRunRecord.status.in_(
                            [OperationStatus.QUEUED.value, OperationStatus.RUNNING.value]
                        ),
                    )
                    .order_by(OperationRunRecord.id.desc())
                )
                if isinstance(record.requested_scope, dict)
                and record.requested_scope.get("daily_report_id") == report_id
                and record.requested_scope.get("rendition") == rendition
            ),
            None,
        )
        if active is not None:
            return active.id
        return OperationRepository(self.session).enqueue(
            OperationType.DAILY_REPORT_AUDIO,
            {"daily_report_id": report_id, "rendition": rendition},
            trigger=trigger,
            in_transaction=True,
        ).id

    @staticmethod
    def _validate_daily_report_audio_request(report_id: int, rendition: str) -> None:
        if isinstance(report_id, bool) or not isinstance(report_id, int) or report_id <= 0:
            raise ValueError("invalid_daily_report_audio_report_id")
        if rendition not in {"decision", "overview"}:
            raise ValueError("invalid_daily_report_audio_rendition")

    def enqueue_source_remediation(
        self,
        *,
        source_id: str,
        candidate_key: str,
        original_probe_id: int,
        baseline_at: datetime,
        trigger: str,
        retry_of_operation_id: int | None = None,
    ) -> int:
        if not source_id or not candidate_key or original_probe_id <= 0:
            raise ValueError("invalid_source_remediation_scope")
        member = self.session.scalar(
            select(SourceRemediationMemberRecord)
            .join(
                SourceRemediationBatchRecord,
                SourceRemediationBatchRecord.id == SourceRemediationMemberRecord.batch_id,
            )
            .where(
                SourceRemediationBatchRecord.baseline_at == baseline_at,
                SourceRemediationMemberRecord.source_id == source_id,
                SourceRemediationMemberRecord.original_probe_id == original_probe_id,
            )
        )
        if member is None:
            raise ValueError("source_not_in_frozen_remediation_batch")
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext('newsradar:source-remediation-enqueue'))"
                )
            )
        active = self.session.scalar(
            select(OperationRunRecord.id).where(
                OperationRunRecord.operation_type == OperationType.SOURCE_REMEDIATION.value,
                OperationRunRecord.status.in_(
                    [OperationStatus.QUEUED.value, OperationStatus.RUNNING.value]
                ),
            )
        )
        if active is not None:
            raise ValueError("active_source_remediation_exists")
        now = self._utcnow()
        record = OperationRepository(self.session).enqueue(
            OperationType.SOURCE_REMEDIATION,
            {
                "source_id": source_id,
                "candidate_key": candidate_key,
                "original_probe_id": original_probe_id,
                "baseline_at": baseline_at.isoformat(),
                "deadline_at": (
                    now + timedelta(seconds=self._settings.operation_timeout_seconds)
                ).isoformat(),
                **(
                    {"retry_of_operation_id": retry_of_operation_id}
                    if retry_of_operation_id is not None
                    else {}
                ),
            },
            trigger=trigger,
        )
        self.session.commit()
        return record.id

    def enqueue_source_catalog_refresh(
        self,
        plan: CatalogRefreshPlan,
        *,
        trigger: str,
        global_concurrency: int = 8,
        provider_concurrency: int = 2,
        retry_of_operation_id: int | None = None,
        abandoned_recovery_of_operation_id: int | None = None,
    ) -> int:
        if not 1 <= global_concurrency <= 16 or not 1 <= provider_concurrency <= 8:
            raise ValueError("invalid_catalog_refresh_concurrency")
        if self.session.in_transaction():
            self.session.commit()
        with self.session.begin():
            self._lock_catalog_refresh_enqueue()
            if self._active_catalog_refresh_id() is not None:
                raise ValueError("active_catalog_refresh_exists")
            record = OperationRepository(self.session).enqueue(
                OperationType.SOURCE_CATALOG_REFRESH,
                self._catalog_refresh_scope(
                    plan,
                    global_concurrency=global_concurrency,
                    provider_concurrency=provider_concurrency,
                    retry_of_operation_id=retry_of_operation_id,
                    abandoned_recovery_of_operation_id=abandoned_recovery_of_operation_id,
                ),
                trigger=trigger,
                in_transaction=True,
            )
            CatalogRefreshRepository(self.session).create_members(record.id, plan)
            record.progress_total = len(plan.members)
            operation_id = record.id
        return operation_id

    def enqueue_daily_autopilot(
        self,
        *,
        plan: WavePlan,
        trigger: str,
    ) -> int:
        """Create one durable, resumable daily-report run and its first continuation."""
        from newsradar.daily_reports.autopilot import DailyAutopilotStage, serialize_wave_plan
        from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository

        if self.session.in_transaction():
            self.session.commit()
        with self.session.begin():
            self._lock_daily_autopilot_enqueue()
            run = DailyAutopilotRepository(self.session, utcnow=self._utcnow).create_run(
                window_hours=plan.window_hours,
                trigger=trigger,
                requested_scope={"wave_plan": serialize_wave_plan(plan)},
            )
            OperationRepository(self.session).enqueue(
                OperationType.DAILY_AUTOPILOT,
                {
                    "daily_autopilot_run_id": run.id,
                    "stage": DailyAutopilotStage.ENQUEUE_CONTENT_WAVE.value,
                },
                trigger=trigger,
                in_transaction=True,
            )
            return run.id

    def enqueue_daily_autopilot_continuation(
        self,
        *,
        run_id: int,
        stage: DailyAutopilotStage,
        trigger: str = "autopilot",
        not_before: datetime | None = None,
    ) -> int:
        from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository

        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise ValueError("invalid_daily_autopilot_run_id")
        if self.session.in_transaction():
            self.session.commit()
        with self.session.begin():
            DailyAutopilotRepository(self.session).get_for_update(run_id)
            operation = OperationRepository(self.session).enqueue(
                OperationType.DAILY_AUTOPILOT,
                {"daily_autopilot_run_id": run_id, "stage": stage.value},
                trigger=trigger,
                in_transaction=True,
                not_before=not_before,
            )
            return operation.id

    def retry_source_catalog_refresh(self, operation_id: int, *, trigger: str) -> int:
        plan = CatalogRefreshRepository(self.session).retryable_plan(operation_id)
        if not plan.members:
            raise ValueError("catalog_refresh_retry_not_allowed")
        return self.enqueue_source_catalog_refresh(
            plan,
            trigger=trigger,
            retry_of_operation_id=operation_id,
        )

    def enqueue_high_value_wave(self, *, plan: WavePlan, trigger: str) -> int:
        if self.session.in_transaction():
            self.session.commit()
        window_end = self._utcnow()
        with self.session.begin():
            self._lock_high_value_wave_enqueue()
            if self._active_high_value_wave_id() is not None:
                raise ValueError("active_high_value_wave_exists")
            record = OperationRepository(self.session).enqueue(
                OperationType.HIGH_VALUE_NEWS_WAVE,
                {
                    "schema_version": 1,
                    "profile_id": plan.profile_id,
                    "profile_digest": plan.digest,
                    "member_count": len(plan.members),
                    "window_hours": plan.window_hours,
                    "trend_days": plan.trend_days,
                    "window_end": window_end.isoformat(),
                    "algorithm_versions": dict(EVENT_ALGORITHM_VERSIONS),
                    "deadline_at": (
                        window_end + timedelta(seconds=self._settings.operation_timeout_seconds)
                    ).isoformat(),
                },
                trigger=trigger,
                in_transaction=True,
            )
            WaveRepository(self.session).create_members(record.id, plan)
            record.progress_total = len(plan.members)
            operation_id = record.id
        return operation_id

    def latest_high_value_wave(self, profile_id: str) -> OperationRunRecord | None:
        """Return the newest durable wave for one profile without touching sources.

        JSON expressions differ between SQLite (tests) and PostgreSQL (runtime), so this
        bounded operation list is filtered in Python rather than relying on a dialect-
        specific JSON operator.  It is only used by the manual due-check command.
        """
        if not profile_id:
            raise ValueError("profile_id_required")
        records = self.session.scalars(
            select(OperationRunRecord)
            .where(OperationRunRecord.operation_type == OperationType.HIGH_VALUE_NEWS_WAVE.value)
            .order_by(OperationRunRecord.id.desc())
        )
        return next(
            (
                record
                for record in records
                if isinstance(record.requested_scope, dict)
                and record.requested_scope.get("profile_id") == profile_id
            ),
            None,
        )

    def _active_high_value_wave_id(self) -> int | None:
        return self.session.scalar(
            select(OperationRunRecord.id).where(
                OperationRunRecord.operation_type == OperationType.HIGH_VALUE_NEWS_WAVE.value,
                OperationRunRecord.status.in_(
                    [OperationStatus.QUEUED.value, OperationStatus.RUNNING.value]
                ),
            )
        )

    def _lock_high_value_wave_enqueue(self) -> None:
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('newsradar:high-value-wave-enqueue'))")
            )

    def recover_abandoned_source_catalog_refresh(
        self, operation_id: int, *, trigger: str, confirm_abandoned: bool
    ) -> int:
        """Create a small new batch only after an operator confirms old claimants stopped."""
        if not confirm_abandoned:
            raise ValueError("confirm_abandoned_required")
        original = self.session.get(OperationRunRecord, operation_id)
        if (
            original is None
            or original.operation_type != OperationType.SOURCE_CATALOG_REFRESH.value
            or original.status in {OperationStatus.QUEUED.value, OperationStatus.RUNNING.value}
        ):
            raise ValueError("catalog_refresh_abandoned_recovery_not_allowed")
        plan = CatalogRefreshRepository(self.session).abandoned_plan(operation_id)
        if not plan.members:
            raise ValueError("catalog_refresh_abandoned_recovery_not_allowed")
        return self.enqueue_source_catalog_refresh(
            plan,
            trigger=trigger,
            abandoned_recovery_of_operation_id=operation_id,
        )

    def _active_catalog_refresh_id(self) -> int | None:
        return self.session.scalar(
            select(OperationRunRecord.id).where(
                OperationRunRecord.operation_type == OperationType.SOURCE_CATALOG_REFRESH.value,
                OperationRunRecord.status.in_(
                    [OperationStatus.QUEUED.value, OperationStatus.RUNNING.value]
                ),
            )
        )

    def _lock_catalog_refresh_enqueue(self) -> None:
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('newsradar:catalog-refresh-enqueue'))")
            )

    def _lock_daily_autopilot_enqueue(self) -> None:
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('newsradar:daily-autopilot-enqueue'))")
            )

    def _catalog_refresh_scope(
        self,
        plan: CatalogRefreshPlan,
        *,
        global_concurrency: int,
        provider_concurrency: int,
        retry_of_operation_id: int | None,
        abandoned_recovery_of_operation_id: int | None,
    ) -> dict[str, object]:
        deadline_at = self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        scope: dict[str, object] = {
            "schema_version": 1,
            "catalog_digest": plan.catalog_digest,
            "catalog_count": len(plan.members),
            "requested_lanes": sorted(lane.value for lane in plan.lane_counts),
            "global_concurrency": global_concurrency,
            "provider_concurrency": provider_concurrency,
            "deadline_at": deadline_at.isoformat(),
        }
        if retry_of_operation_id is not None:
            scope["retry_of_operation_id"] = retry_of_operation_id
        if abandoned_recovery_of_operation_id is not None:
            scope["abandoned_recovery_of_operation_id"] = abandoned_recovery_of_operation_id
        return scope

    def retry_source_remediation(self, operation_id: int, *, trigger: str) -> int:
        """Permit one deliberately requested retry, only for transport failures."""
        original = self.session.get(OperationRunRecord, operation_id)
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        category = (
            original.result_summary.get("category")
            if original is not None and isinstance(original.result_summary, dict)
            else None
        )
        existing_retry = any(
            record.requested_scope.get("retry_of_operation_id") == operation_id
            for record in self.session.scalars(
                select(OperationRunRecord).where(
                    OperationRunRecord.operation_type == OperationType.SOURCE_REMEDIATION.value
                )
            )
        )
        if (
            original is None
            or original.operation_type != OperationType.SOURCE_REMEDIATION.value
            or original.status not in terminal_statuses
            or category != "network_transient"
            or existing_retry
        ):
            raise ValueError("source_remediation_retry_not_allowed")
        scope = original.requested_scope
        return self.enqueue_source_remediation(
            source_id=str(scope.get("source_id", "")),
            candidate_key=str(scope.get("candidate_key", "")),
            original_probe_id=int(scope.get("original_probe_id", 0)),
            baseline_at=datetime.fromisoformat(str(scope.get("baseline_at"))),
            trigger=trigger,
            retry_of_operation_id=operation_id,
        )

    def enqueue_event_pipeline(self, *, window_hours: int, trigger: str) -> int:
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        window_end = self._utcnow()
        versions = dict(EVENT_ALGORITHM_VERSIONS)
        key_parts = {
            "window_end": window_end.isoformat(),
            "window_hours": window_hours,
            "versions": versions,
        }
        scope = {
            "actor": trigger,
            "window_hours": window_hours,
            "algorithm_versions": versions,
            "window_end": window_end.isoformat(),
            "idempotency_key": "event-pipeline:"
            + sha256(dumps(key_parts, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                window_end + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(
            OperationType.EVENT_PIPELINE, scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def enqueue_event_merge_scan(self, trigger: str) -> int:
        if not trigger:
            raise ValueError("event_merge_scan_trigger_required")
        window_end = self._utcnow()
        versions = dict(EVENT_ALGORITHM_VERSIONS)
        key_parts = {
            "algorithm_version": EVENT_MERGE_RULE_VERSION,
            "algorithm_versions": versions,
            "window_end": window_end.isoformat(),
        }
        scope = {
            "actor": trigger,
            "algorithm_version": EVENT_MERGE_RULE_VERSION,
            "algorithm_versions": versions,
            "window_end": window_end.isoformat(),
            "idempotency_key": "event-merge-scan:"
            + sha256(dumps(key_parts, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                window_end + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(
            OperationType.EVENT_MERGE_SCAN, scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def enqueue_event_merge_decision(
        self,
        candidate_id: int,
        decision: Literal["apply", "confirm", "dismiss", "recheck"],
        trigger: str,
    ) -> int:
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("event_merge_candidate_required")
        if decision not in {"apply", "confirm", "dismiss", "recheck"}:
            raise ValueError("event_merge_invalid_decision")
        if not trigger:
            raise ValueError("event_merge_trigger_required")
        now = self._utcnow()
        scope = {
            "candidate_id": candidate_id,
            "decision": decision,
            "actor": trigger,
            "idempotency_key": f"event-merge-decision:{decision}:{candidate_id}:"
            + sha256(f"{trigger}:{now.isoformat()}".encode()).hexdigest(),
            "deadline_at": (
                now + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(
            OperationType.EVENT_MERGE, scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def enqueue_event_action(
        self, action: str, event_id: int, payload: dict | None, trigger: str
    ) -> int:
        if action == "merge":
            raise ValueError("event_merge_candidate_required")
        operation_type = {
            "recluster": OperationType.EVENT_RECLUSTER,
            "enrich": OperationType.EVENT_ENRICH,
            "split": OperationType.EVENT_SPLIT,
            "exclude": OperationType.EVENT_EXCLUDE,
        }.get(action)
        if operation_type is None or event_id <= 0:
            raise ValueError("invalid event action")
        now = self._utcnow()
        payload_data = payload or {}
        scope = {
            "event_id": event_id,
            "payload": payload_data,
            **{key: value for key, value in payload_data.items() if key != "actor"},
            "actor": trigger,
            "idempotency_key": f"event-action:{action}:{event_id}:"
            + sha256(dumps(payload_data, sort_keys=True).encode()).hexdigest(),
            "deadline_at": (
                now + timedelta(seconds=self._settings.operation_timeout_seconds)
            ).isoformat(),
        }
        record = OperationRepository(self.session).enqueue(operation_type, scope, trigger=trigger)
        self.session.commit()
        return record.id

    def retry(self, operation_id: int, *, trigger: str) -> int:
        original = self.session.get(OperationRunRecord, operation_id)
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        if (
            original is None
            or original.status not in terminal_statuses
            or original.operation_type == OperationType.SOURCE_REMEDIATION.value
            or not is_retryable_error(original.error_code)
        ):
            raise ValueError("operation is not retryable")
        scope = dict(original.requested_scope)
        scope["retry_of_operation_id"] = operation_id
        scope["deadline_at"] = (
            self._utcnow() + timedelta(seconds=self._settings.operation_timeout_seconds)
        ).isoformat()
        record = OperationRepository(self.session).enqueue(
            OperationType(original.operation_type), scope, trigger=trigger
        )
        self.session.commit()
        return record.id

    def cancel(self, operation_id: int) -> bool:
        result = OperationRepository(self.session).request_cancel(operation_id)
        self.session.commit()
        return result

    def wait_for_terminal(
        self, operation_id: int, *, timeout_seconds: float = 1800, poll_seconds: float = 0.25
    ) -> OperationRunRecord:
        deadline = self._clock() + timeout_seconds
        terminal_statuses = {item.value for item in OperationStatus.terminal()}
        while self._clock() < deadline:
            self.session.expire_all()
            record = self.session.get(OperationRunRecord, operation_id)
            if record is None:
                raise LookupError(operation_id)
            if record.status in terminal_statuses:
                return record
            self._sleeper(poll_seconds)
        raise TimeoutError(f"operation {operation_id} did not finish within {timeout_seconds}s")
