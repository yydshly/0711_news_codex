from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    ProviderDefinitionRecord,
    ProviderProbeRunRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceRiskAssessmentRecord,
)
from newsradar.web.i18n import explain_failure, zh_label
from newsradar.web.viewmodels import (
    AccessMethodView,
    DashboardSummary,
    GapGroup,
    GapTarget,
    ProbeRow,
    ProviderDetail,
    ProviderRow,
    RiskView,
    TargetDetail,
    TargetRow,
)

FREE_COST_TIERS = {"free", "free_quota", "freemium"}
SUCCESS_OUTCOMES = {"success"}
_GAP_ORDER = (
    "requires_credentials",
    "requires_approval",
    "requires_payment",
    "manual_only",
    "unavailable",
)
_NO_PROBE_LABEL = "尚未探测"
_NO_ALTERNATIVE = "无已审核替代路径"


class DashboardQueryService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def summary(self) -> DashboardSummary:
        providers = self._session.scalars(select(ProviderDefinitionRecord)).all()
        targets = self._session.scalars(select(SourceDefinitionRecord)).all()
        runs = self._content_runs()
        runs_by_source: dict[str, list[SourceProbeRunRecord]] = defaultdict(list)
        for run in runs:
            runs_by_source[run.source_id].append(run)

        latest_content = runs[0].finished_at if runs else None
        latest_capability = self._session.scalar(
            select(func.max(ProviderProbeRunRecord.checked_at))
        )
        latest_probe_at = max(
            (value for value in (latest_content, latest_capability) if value is not None),
            default=None,
        )
        provider_cost = {provider.id: provider.cost_tier for provider in providers}
        category_counts = Counter(provider.category for provider in providers)
        return DashboardSummary(
            provider_count=len(providers),
            target_count=len(targets),
            free_direct_count=sum(
                target.coverage_mode == "direct"
                and target.availability == "ready"
                and provider_cost.get(target.provider_id) in FREE_COST_TIERS
                for target in targets
            ),
            indirect_count=sum(target.coverage_mode == "indirect" for target in targets),
            blocked_count=sum(target.availability != "ready" for target in targets),
            three_success_count=sum(
                len(source_runs[:3]) == 3
                and all(run.outcome in SUCCESS_OUTCOMES for run in source_runs[:3])
                for source_runs in runs_by_source.values()
            ),
            category_counts=tuple(sorted(category_counts.items())),
            latest_probe_at=latest_probe_at,
        )

    def providers(self, filters: Mapping[str, Any] | None = None) -> list[ProviderRow]:
        filters = filters or {}
        statement: Select[tuple[ProviderDefinitionRecord]] = select(ProviderDefinitionRecord)
        if category := filters.get("category"):
            statement = statement.where(ProviderDefinitionRecord.category == category)
        if availability := filters.get("availability"):
            statement = statement.where(ProviderDefinitionRecord.availability == availability)
        if cost_tier := filters.get("cost_tier"):
            statement = statement.where(ProviderDefinitionRecord.cost_tier == cost_tier)
        if query := self._normalized_query(filters.get("q")):
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    ProviderDefinitionRecord.name.ilike(pattern),
                    ProviderDefinitionRecord.id.ilike(pattern),
                )
            )
        records = self._session.scalars(statement.order_by(ProviderDefinitionRecord.name)).all()
        targets = self._session.scalars(select(SourceDefinitionRecord)).all()
        targets_by_provider: dict[str, list[SourceDefinitionRecord]] = defaultdict(list)
        for target in targets:
            targets_by_provider[target.provider_id].append(target)
        latest = self._latest_capability_runs()
        return [
            self._provider_row(
                record, targets_by_provider.get(record.id, []), latest.get(record.id)
            )
            for record in records
        ]

    def provider_detail(self, provider_id: str) -> ProviderDetail | None:
        provider = self._session.get(ProviderDefinitionRecord, provider_id)
        if provider is None:
            return None
        targets = self._session.scalars(
            select(SourceDefinitionRecord)
            .where(SourceDefinitionRecord.provider_id == provider_id)
            .order_by(SourceDefinitionRecord.name)
        ).all()
        target_rows = tuple(self._target_rows_for_records(targets))
        capability_records = self._session.scalars(
            select(ProviderProbeRunRecord)
            .where(ProviderProbeRunRecord.provider_id == provider_id)
            .order_by(ProviderProbeRunRecord.checked_at.desc(), ProviderProbeRunRecord.id.desc())
        ).all()
        probes = tuple(
            self._provider_probe_row(record, provider.name) for record in capability_records
        )
        latest = capability_records[0] if capability_records else None
        return ProviderDetail(
            row=self._provider_row(provider, targets, latest),
            homepage=provider.homepage,
            docs_url=provider.docs_url,
            terms_url=provider.terms_url,
            auth_mode=provider.auth_mode,
            auth_label=zh_label("auth_mode", provider.auth_mode),
            capabilities=tuple(provider.capabilities),
            required_env=tuple(provider.required_env),
            evidence=tuple(provider.evidence),
            unlock_requirements=tuple(provider.unlock_requirements),
            notes=provider.notes,
            targets=target_rows,
            probes=probes,
        )

    def targets(self, filters: Mapping[str, Any] | None = None) -> list[TargetRow]:
        filters = filters or {}
        statement: Select[tuple[SourceDefinitionRecord]] = select(SourceDefinitionRecord)
        for key, column in (
            ("provider_id", SourceDefinitionRecord.provider_id),
            ("target_type", SourceDefinitionRecord.target_type),
            ("coverage_mode", SourceDefinitionRecord.coverage_mode),
            ("availability", SourceDefinitionRecord.availability),
        ):
            if value := filters.get(key):
                statement = statement.where(column == value)
        if query := self._normalized_query(filters.get("q")):
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    SourceDefinitionRecord.name.ilike(pattern),
                    SourceDefinitionRecord.id.ilike(pattern),
                )
            )
        records = self._session.scalars(statement.order_by(SourceDefinitionRecord.name)).all()
        return self._target_rows_for_records(records)

    def target_detail(self, source_id: str) -> TargetDetail | None:
        source = self._session.get(SourceDefinitionRecord, source_id)
        if source is None:
            return None
        row = self._target_rows_for_records([source])[0]
        access_records = self._session.scalars(
            select(SourceAccessMethodRecord)
            .where(SourceAccessMethodRecord.source_id == source_id)
            .order_by(SourceAccessMethodRecord.priority)
        ).all()
        risk_record = self._latest_risks([source_id]).get(source_id)
        probe_records = self._session.scalars(
            select(SourceProbeRunRecord)
            .where(SourceProbeRunRecord.source_id == source_id)
            .order_by(SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc())
            .limit(3)
        ).all()
        return TargetDetail(
            row=row,
            official_identity_url=source.official_identity_url,
            reviewed_at=source.reviewed_at,
            status=source.status,
            status_label=zh_label("status", source.status),
            nature=source.nature,
            nature_label=zh_label("nature", source.nature),
            language=source.language,
            roles=tuple((role, zh_label("role", role)) for role in source.roles),
            topics=tuple(source.topics),
            expected_fields=tuple(source.expected_fields),
            unlock_requirements=tuple(source.unlock_requirements),
            notes=source.notes,
            access_methods=tuple(self._access_method_view(record) for record in access_records),
            risk=self._risk_view(risk_record) if risk_record else None,
            recent_probes=tuple(
                self._source_probe_row(record, source.name) for record in probe_records
            ),
        )

    def probes(self, filters: Mapping[str, Any] | None = None) -> list[ProbeRow]:
        filters = filters or {}
        requested_type = filters.get("probe_type")
        rows: list[tuple[ProbeRow, str]] = []
        if requested_type in (None, "content"):
            content_statement = (
                select(
                    SourceProbeRunRecord,
                    SourceDefinitionRecord.name,
                    SourceDefinitionRecord.provider_id,
                )
                .join(
                    SourceDefinitionRecord,
                    SourceDefinitionRecord.id == SourceProbeRunRecord.source_id,
                )
                .order_by(SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc())
            )
            content_statement = self._apply_probe_record_filters(
                content_statement,
                SourceProbeRunRecord.outcome,
                SourceProbeRunRecord.finished_at,
                filters,
            )
            if provider_id := filters.get("provider_id"):
                content_statement = content_statement.where(
                    SourceDefinitionRecord.provider_id == provider_id
                )
            rows.extend(
                (self._source_probe_row(record, name), provider_id)
                for record, name, provider_id in self._session.execute(content_statement)
            )
        if requested_type in (None, "capability"):
            capability_statement = (
                select(ProviderProbeRunRecord, ProviderDefinitionRecord.name)
                .join(
                    ProviderDefinitionRecord,
                    ProviderDefinitionRecord.id == ProviderProbeRunRecord.provider_id,
                )
                .order_by(
                    ProviderProbeRunRecord.checked_at.desc(), ProviderProbeRunRecord.id.desc()
                )
            )
            capability_statement = self._apply_probe_record_filters(
                capability_statement,
                ProviderProbeRunRecord.outcome,
                ProviderProbeRunRecord.checked_at,
                filters,
            )
            if provider_id := filters.get("provider_id"):
                capability_statement = capability_statement.where(
                    ProviderProbeRunRecord.provider_id == provider_id
                )
            rows.extend(
                (self._provider_probe_row(record, name), record.provider_id)
                for record, name in self._session.execute(capability_statement)
            )
        return [
            row
            for row, _provider_id in sorted(rows, key=lambda item: item[0].checked_at, reverse=True)
        ]

    def gap_groups(self) -> tuple[GapGroup, ...]:
        providers = {
            provider.id: provider
            for provider in self._session.scalars(select(ProviderDefinitionRecord)).all()
        }
        blocked = self._session.scalars(
            select(SourceDefinitionRecord)
            .where(SourceDefinitionRecord.availability.in_(_GAP_ORDER))
            .order_by(SourceDefinitionRecord.name)
        ).all()
        indirect_by_provider: dict[str, list[SourceDefinitionRecord]] = defaultdict(list)
        for source in self._session.scalars(
            select(SourceDefinitionRecord).where(
                SourceDefinitionRecord.coverage_mode == "indirect",
                SourceDefinitionRecord.availability == "ready",
            )
        ):
            indirect_by_provider[source.provider_id].append(source)
        risks = self._latest_risks([source.id for source in blocked])
        grouped: dict[str, list[GapTarget]] = defaultdict(list)
        for source in blocked:
            provider = providers[source.provider_id]
            alternatives = indirect_by_provider.get(source.provider_id, [])
            evidence = list(provider.evidence)
            if risk := risks.get(source.id):
                evidence.extend(risk.evidence)
            grouped[source.availability].append(
                GapTarget(
                    source_id=source.id,
                    name=source.name,
                    provider_id=provider.id,
                    provider_name=provider.name,
                    impact=f"{source.name} 当前仅登记，尚不可直接读取内容",
                    alternative=("、".join(item.name for item in alternatives) or _NO_ALTERNATIVE),
                    cost_label=zh_label("cost_tier", provider.cost_tier),
                    unlock_requirements=tuple(
                        source.unlock_requirements or provider.unlock_requirements
                    ),
                    evidence=tuple(dict.fromkeys(evidence)),
                )
            )
        return tuple(
            GapGroup(
                availability=availability,
                label=zh_label("availability", availability),
                target_count=len(grouped[availability]),
                targets=tuple(grouped[availability]),
            )
            for availability in _GAP_ORDER
            if grouped[availability]
        )

    def _provider_row(
        self,
        provider: ProviderDefinitionRecord,
        targets: Sequence[SourceDefinitionRecord],
        latest: ProviderProbeRunRecord | None,
    ) -> ProviderRow:
        return ProviderRow(
            provider_id=provider.id,
            name=provider.name,
            category=provider.category,
            category_label=zh_label("provider_category", provider.category),
            cost_tier=provider.cost_tier,
            cost_label=zh_label("cost_tier", provider.cost_tier),
            availability=provider.availability,
            availability_label=zh_label("availability", provider.availability),
            target_count=len(targets),
            direct_count=sum(target.coverage_mode == "direct" for target in targets),
            indirect_count=sum(target.coverage_mode == "indirect" for target in targets),
            latest_outcome=latest.outcome if latest else None,
            latest_outcome_label=(
                zh_label("outcome", latest.outcome) if latest else _NO_PROBE_LABEL
            ),
            reviewed_at=provider.reviewed_at,
            auth_mode=provider.auth_mode,
            auth_label=zh_label("auth_mode", provider.auth_mode),
            capabilities=tuple(provider.capabilities),
        )

    def _target_rows_for_records(
        self, records: Sequence[SourceDefinitionRecord]
    ) -> list[TargetRow]:
        if not records:
            return []
        source_ids = [record.id for record in records]
        provider_ids = {record.provider_id for record in records}
        providers = {
            provider.id: provider.name
            for provider in self._session.scalars(
                select(ProviderDefinitionRecord).where(
                    ProviderDefinitionRecord.id.in_(provider_ids)
                )
            )
        }
        methods = {
            method.source_id: method
            for method in self._session.scalars(
                select(SourceAccessMethodRecord).where(
                    SourceAccessMethodRecord.source_id.in_(source_ids),
                    SourceAccessMethodRecord.priority == 1,
                )
            )
        }
        risks = self._latest_risks(source_ids)
        latest_runs = self._latest_content_runs(source_ids)
        rows = []
        for source in records:
            method = methods.get(source.id)
            risk = risks.get(source.id)
            latest = latest_runs.get(source.id)
            rows.append(
                TargetRow(
                    source_id=source.id,
                    name=source.name,
                    provider_id=source.provider_id,
                    provider_name=providers.get(source.provider_id, source.provider_id),
                    target_type=source.target_type,
                    target_type_label=zh_label("target_type", source.target_type),
                    coverage_mode=source.coverage_mode,
                    coverage_label=zh_label("coverage_mode", source.coverage_mode),
                    availability=source.availability,
                    availability_label=zh_label("availability", source.availability),
                    access_kind=method.kind if method else None,
                    access_label=zh_label("access_kind", method.kind) if method else "尚未配置",
                    risk_total=risk.total if risk else None,
                    latest_content_at=latest.finished_at if latest else None,
                    latest_outcome=latest.outcome if latest else None,
                    latest_outcome_label=(
                        zh_label("outcome", latest.outcome) if latest else _NO_PROBE_LABEL
                    ),
                    roles=tuple(source.roles),
                    role_labels=tuple(zh_label("role", role) for role in source.roles),
                )
            )
        return rows

    def _content_runs(self) -> list[SourceProbeRunRecord]:
        return list(
            self._session.scalars(
                select(SourceProbeRunRecord).order_by(
                    SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc()
                )
            )
        )

    def _latest_capability_runs(self) -> dict[str, ProviderProbeRunRecord]:
        latest: dict[str, ProviderProbeRunRecord] = {}
        for run in self._session.scalars(
            select(ProviderProbeRunRecord).order_by(
                ProviderProbeRunRecord.checked_at.desc(), ProviderProbeRunRecord.id.desc()
            )
        ):
            latest.setdefault(run.provider_id, run)
        return latest

    def _latest_risks(self, source_ids: Sequence[str]) -> dict[str, SourceRiskAssessmentRecord]:
        if not source_ids:
            return {}
        ranked = (
            select(
                SourceRiskAssessmentRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=SourceRiskAssessmentRecord.source_id,
                    order_by=(
                        SourceRiskAssessmentRecord.assessed_at.desc(),
                        SourceRiskAssessmentRecord.id.desc(),
                    ),
                )
                .label("history_rank"),
            )
            .where(SourceRiskAssessmentRecord.source_id.in_(source_ids))
            .subquery()
        )
        records = self._session.scalars(
            select(SourceRiskAssessmentRecord)
            .join(ranked, SourceRiskAssessmentRecord.id == ranked.c.record_id)
            .where(ranked.c.history_rank == 1)
        )
        return {record.source_id: record for record in records}

    def _latest_content_runs(
        self, source_ids: Sequence[str]
    ) -> dict[str, SourceProbeRunRecord]:
        if not source_ids:
            return {}
        ranked = (
            select(
                SourceProbeRunRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=SourceProbeRunRecord.source_id,
                    order_by=(
                        SourceProbeRunRecord.finished_at.desc(),
                        SourceProbeRunRecord.id.desc(),
                    ),
                )
                .label("history_rank"),
            )
            .where(SourceProbeRunRecord.source_id.in_(source_ids))
            .subquery()
        )
        records = self._session.scalars(
            select(SourceProbeRunRecord)
            .join(ranked, SourceProbeRunRecord.id == ranked.c.record_id)
            .where(ranked.c.history_rank == 1)
        )
        return {record.source_id: record for record in records}

    @staticmethod
    def _source_probe_row(run: SourceProbeRunRecord, object_name: str) -> ProbeRow:
        completeness = run.metrics.get("field_completeness")
        return ProbeRow(
            probe_id=f"content-{run.id}",
            object_id=run.source_id,
            object_name=object_name,
            probe_type="content",
            probe_type_label="内容探测",
            outcome=run.outcome,
            outcome_label=zh_label("outcome", run.outcome),
            checked_at=run.finished_at,
            http_status=run.http_status,
            latency_ms=run.latency_ms,
            completeness=float(completeness) if completeness is not None else None,
            reason_zh=(
                zh_label("outcome", run.outcome)
                if run.outcome in SUCCESS_OUTCOMES
                else explain_failure(run.reason, run.http_status, run.error_code)
            ),
            reason_raw=run.reason,
        )

    @staticmethod
    def _provider_probe_row(run: ProviderProbeRunRecord, object_name: str) -> ProbeRow:
        return ProbeRow(
            probe_id=f"capability-{run.id}",
            object_id=run.provider_id,
            object_name=object_name,
            probe_type="capability",
            probe_type_label=zh_label("probe_type", "capability"),
            outcome=run.outcome,
            outcome_label=zh_label("outcome", run.outcome),
            checked_at=run.checked_at,
            http_status=run.http_status,
            latency_ms=run.latency_ms,
            completeness=None,
            reason_zh=(
                zh_label("outcome", run.outcome)
                if run.outcome in SUCCESS_OUTCOMES
                else explain_failure(run.reason, run.http_status, None)
            ),
            reason_raw=run.reason,
        )

    @staticmethod
    def _access_method_view(record: SourceAccessMethodRecord) -> AccessMethodView:
        return AccessMethodView(
            kind=record.kind,
            kind_label=zh_label("access_kind", record.kind),
            url=record.url,
            priority=record.priority,
            requires_manual_approval=record.requires_manual_approval,
            auth_env=record.auth_env,
        )

    @staticmethod
    def _risk_view(record: SourceRiskAssessmentRecord) -> RiskView:
        return RiskView(
            terms=record.terms,
            authentication=record.authentication,
            stability=record.stability,
            data_quality=record.data_quality,
            operating_cost=record.operating_cost,
            total=record.total,
            evidence=tuple(record.evidence),
            hard_block_reason=record.hard_block_reason,
            assessed_at=record.assessed_at,
        )

    @staticmethod
    def _normalized_query(value: Any) -> str:
        return str(value).strip()[:100] if value is not None else ""

    @staticmethod
    def _apply_probe_record_filters(
        statement: Select[Any],
        outcome_column: Any,
        timestamp_column: Any,
        filters: Mapping[str, Any],
    ) -> Select[Any]:
        if outcome := filters.get("outcome"):
            statement = statement.where(outcome_column == outcome)
        if from_value := DashboardQueryService._date_boundary(filters.get("from_date"), end=False):
            statement = statement.where(timestamp_column >= from_value)
        if to_value := DashboardQueryService._date_boundary(filters.get("to_date"), end=True):
            statement = statement.where(timestamp_column <= to_value)
        return statement

    @staticmethod
    def _date_boundary(value: Any, *, end: bool) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            value = date.fromisoformat(value)
        if isinstance(value, date):
            return datetime.combine(value, time.max if end else time.min)
        raise TypeError("probe date filter must be a date, datetime, ISO date string, or None")
