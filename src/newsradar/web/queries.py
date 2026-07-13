from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import Select, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from newsradar.db.models import (
    ProviderDefinitionRecord,
    ProviderProbeRunRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceRiskAssessmentRecord,
    SourceResearchProfileRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
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
    ResearchCandidateView,
    ResearchTargetView,
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

    def research_targets(self) -> list[ResearchTargetView]:
        """Read-only research catalog, loaded in bounded batches (no per-target queries)."""
        sources = self._session.scalars(select(SourceDefinitionRecord).order_by(SourceDefinitionRecord.name)).all()
        if not sources:
            return []
        ids = [s.id for s in sources]
        providers = {p.id: p for p in self._session.scalars(select(ProviderDefinitionRecord).where(ProviderDefinitionRecord.id.in_({s.provider_id for s in sources}))).all()}
        profiles = {p.source_id: p for p in self._session.scalars(select(SourceResearchProfileRecord).where(SourceResearchProfileRecord.source_id.in_(ids))).all()}
        candidates = self._session.scalars(select(SourceAcquisitionCandidateRecord).where(SourceAcquisitionCandidateRecord.source_id.in_(ids), SourceAcquisitionCandidateRecord.is_current.is_(True)).order_by(SourceAcquisitionCandidateRecord.source_id, SourceAcquisitionCandidateRecord.reviewed_at.desc())).all()
        probes = self._session.scalars(select(SourceAcquisitionProbeRunRecord).where(SourceAcquisitionProbeRunRecord.candidate_id.in_([c.id for c in candidates])).order_by(SourceAcquisitionProbeRunRecord.completed_at.desc())).all() if candidates else []
        probes_by_candidate={}
        for p in probes: probes_by_candidate.setdefault(p.candidate_id, p)
        by_source: dict[str, list[SourceAcquisitionCandidateRecord]] = defaultdict(list)
        for c in candidates: by_source[c.source_id].append(c)
        return [self._research_view(s, providers[s.provider_id].name if s.provider_id in providers else s.provider_id, profiles.get(s.id), by_source.get(s.id, []), providers[s.provider_id].availability if s.provider_id in providers else "unknown", [probes_by_candidate[c.id] for c in by_source.get(s.id, []) if c.id in probes_by_candidate]) for s in sources]

    def research_target(self, source_id: str) -> ResearchTargetView | None:
        source = self._session.get(SourceDefinitionRecord, source_id)
        if source is None:
            return None
        provider = self._session.get(ProviderDefinitionRecord, source.provider_id)
        profile = self._session.get(SourceResearchProfileRecord, source_id)
        candidates = self._session.scalars(select(SourceAcquisitionCandidateRecord).where(SourceAcquisitionCandidateRecord.source_id == source_id, SourceAcquisitionCandidateRecord.is_current.is_(True)).order_by(SourceAcquisitionCandidateRecord.reviewed_at.desc())).all()
        probes = self._session.scalars(select(SourceAcquisitionProbeRunRecord).where(SourceAcquisitionProbeRunRecord.candidate_id.in_([c.id for c in candidates])).order_by(SourceAcquisitionProbeRunRecord.completed_at.desc())).all() if candidates else []
        return self._research_view(source, provider.name if provider else source.provider_id, profile, candidates, provider.availability if provider else "unknown", probes)

    research_dashboard = research_targets

    @staticmethod
    def _research_view(source, provider_name, profile, candidates, provider_availability="unknown", probes=()):
        status = profile.status if profile else "unknown"
        status_label = {"verified":"已验证", "needs_research":"待研究", "placeholder":"占位", "duplicate":"重复", "retired":"已退役", "unknown":"未知"}.get(status, "未知")
        officiality = {"official":"官方", "documented_public":"有公开文档", "unofficial_library":"非官方库", "third_party_service":"第三方服务"}
        decisions = {"primary":"首选", "supplement":"补充", "fallback":"备用", "manual_only":"仅人工", "rejected":"淘汰"}
        auth = {"none":"无需认证", "api_key":"API Key", "oauth":"OAuth", "approval":"审批", "payment":"付费", "login_cookie":"登录 Cookie"}
        kinds = {"rss":"RSS", "atom":"Atom", "rest_api":"REST API", "public_api":"公开 API", "html":"HTML 网页", "sitemap":"站点地图", "library":"第三方库", "service":"第三方服务", "manual":"人工"}
        samples = {"not_run":"未采样", "succeeded":"已采样", "partial":"部分采样", "failed":"采样失败", "blocked":"采样受限"}
        latest = {}
        for probe in probes:
            latest.setdefault(probe.candidate_id, probe)
        role_labels={"discovery":"发现","evidence":"证据","engagement":"互动","context":"背景"}
        views = tuple(ResearchCandidateView(key=c.candidate_key, kind=kinds.get(c.kind, "未知"), implementation=c.implementation, officiality=c.officiality, officiality_label=officiality.get(c.officiality, "未知"), authentication=c.authentication, authentication_label=auth.get(c.authentication, "未知"), roles=tuple(role_labels.get(r, "未知") for r in (c.roles or ())), fields=tuple(c.fields or ()), limitations=tuple(c.limitations or ()), evidence=tuple(c.evidence or ()), sample_status=samples.get(c.sample_status, "未知"), decision=c.decision, decision_label=decisions.get(c.decision, "未知"), sample_count=latest.get(c.id).sample_count if latest.get(c.id) else None, latest_probe_at=latest.get(c.id).completed_at if latest.get(c.id) else None, field_completeness=(len(latest.get(c.id).fields_present)/len(c.fields) if latest.get(c.id) and c.fields else None), latest_probe_outcome=latest.get(c.id).outcome if latest.get(c.id) else None, latest_probe_label={"succeeded":"已成功","partial":"部分成功","blocked":"受限","failed":"失败"}.get(latest.get(c.id).outcome, "未知") if latest.get(c.id) else "尚未探测") for c in candidates)
        target_types={"publisher_feed","account","channel","keyword","topic","community","search_query","trend","market"}; coverages={"direct","indirect","catalog_only"}; availabilities={"ready","requires_credentials","requires_approval","requires_payment","manual_only","unavailable"}
        return ResearchTargetView(source_id=source.id, name=source.name, provider_name=provider_name, provider_availability_label=zh_label("availability", provider_availability) if provider_availability in availabilities else "未知", target_status_label=zh_label("status", source.status) if source.status in {"candidate","active","degraded","paused","disabled"} else "未知", nature_label=zh_label("nature", source.nature) if source.nature in {"first_party","research","community","professional_media","aggregator","social"} else "未知", target_type_label=zh_label("target_type", source.target_type) if source.target_type in target_types else "未知", coverage_label=zh_label("coverage_mode", source.coverage_mode) if source.coverage_mode in coverages else "未知", availability_label=zh_label("availability", source.availability) if source.availability in availabilities else "未知", research_status=status, research_status_label=status_label, wanted_information=tuple(profile.wanted_information or ()) if profile else (), conclusion=profile.conclusion if profile else None, no_fallback_reason=profile.no_fallback_reason if profile else None, candidates=views)

    def summary(self) -> DashboardSummary:
        provider_count = self._session.scalar(select(func.count(ProviderDefinitionRecord.id))) or 0
        target_count = self._session.scalar(select(func.count(SourceDefinitionRecord.id))) or 0
        runs = self._recent_content_runs(3)
        runs_by_source: dict[str, list[SourceProbeRunRecord]] = defaultdict(list)
        for run in runs:
            runs_by_source[run.source_id].append(run)

        category_counts = self._session.execute(
            select(ProviderDefinitionRecord.category, func.count(ProviderDefinitionRecord.id))
            .group_by(ProviderDefinitionRecord.category)
            .order_by(ProviderDefinitionRecord.category)
        ).all()
        free_direct_count = self._session.scalar(
            select(func.count(SourceDefinitionRecord.id))
            .join(
                ProviderDefinitionRecord,
                ProviderDefinitionRecord.id == SourceDefinitionRecord.provider_id,
            )
            .where(
                SourceDefinitionRecord.coverage_mode == "direct",
                SourceDefinitionRecord.availability == "ready",
                ProviderDefinitionRecord.cost_tier.in_(FREE_COST_TIERS),
            )
        ) or 0
        indirect_count = self._session.scalar(
            select(func.count(SourceDefinitionRecord.id)).where(
                SourceDefinitionRecord.coverage_mode == "indirect"
            )
        ) or 0
        blocked_count = self._session.scalar(
            select(func.count(SourceDefinitionRecord.id)).where(
                SourceDefinitionRecord.availability != "ready"
            )
        ) or 0
        return DashboardSummary(
            provider_count=provider_count,
            target_count=target_count,
            free_direct_count=free_direct_count,
            indirect_count=indirect_count,
            blocked_count=blocked_count,
            three_success_count=sum(
                len(source_runs[:3]) == 3
                and all(run.outcome in SUCCESS_OUTCOMES for run in source_runs[:3])
                for source_runs in runs_by_source.values()
            ),
            category_counts=tuple(category_counts),
            latest_probe_at=self.latest_probe_at(),
        )

    def latest_probe_at(self) -> datetime | None:
        latest_content = self._session.scalar(select(func.max(SourceProbeRunRecord.finished_at)))
        latest_capability = self._session.scalar(
            select(func.max(ProviderProbeRunRecord.checked_at))
        )
        return max(
            (value for value in (latest_content, latest_capability) if value is not None),
            default=None,
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
            .limit(3)
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
        if filters.get("free_direct"):
            statement = statement.join(
                ProviderDefinitionRecord,
                ProviderDefinitionRecord.id == SourceDefinitionRecord.provider_id,
            ).where(
                SourceDefinitionRecord.coverage_mode == "direct",
                SourceDefinitionRecord.availability == "ready",
                ProviderDefinitionRecord.cost_tier.in_(FREE_COST_TIERS),
            )
        if filters.get("three_success"):
            statement = statement.where(
                SourceDefinitionRecord.id.in_(self._three_success_source_ids())
            )
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
        page = max(int(filters.get("page", 1)), 1)
        page_size = min(max(int(filters.get("page_size", 100)), 1), 200)
        branches = []
        if requested_type in (None, "content"):
            content_statement = (
                select(
                    literal("content").label("probe_type"),
                    SourceProbeRunRecord.id.label("record_id"),
                    SourceProbeRunRecord.finished_at.label("checked_at"),
                )
                .join(
                    SourceDefinitionRecord,
                    SourceDefinitionRecord.id == SourceProbeRunRecord.source_id,
                )
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
            branches.append(content_statement)
        if requested_type in (None, "capability"):
            capability_statement = (
                select(
                    literal("capability").label("probe_type"),
                    ProviderProbeRunRecord.id.label("record_id"),
                    ProviderProbeRunRecord.checked_at.label("checked_at"),
                )
                .join(
                    ProviderDefinitionRecord,
                    ProviderDefinitionRecord.id == ProviderProbeRunRecord.provider_id,
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
            branches.append(capability_statement)
        if not branches:
            return []
        unified = union_all(*branches).subquery()
        selected = self._session.execute(
            select(unified.c.probe_type, unified.c.record_id)
            .order_by(unified.c.checked_at.desc(), unified.c.record_id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all()
        content_ids = [record_id for probe_type, record_id in selected if probe_type == "content"]
        capability_ids = [
            record_id for probe_type, record_id in selected if probe_type == "capability"
        ]
        content_rows = {
            record.id: self._source_probe_row(record, name)
            for record, name in self._session.execute(
                select(SourceProbeRunRecord, SourceDefinitionRecord.name)
                .join(
                    SourceDefinitionRecord,
                    SourceDefinitionRecord.id == SourceProbeRunRecord.source_id,
                )
                .where(SourceProbeRunRecord.id.in_(content_ids))
            )
        }
        capability_rows = {
            record.id: self._provider_probe_row(record, name)
            for record, name in self._session.execute(
                select(ProviderProbeRunRecord, ProviderDefinitionRecord.name)
                .join(
                    ProviderDefinitionRecord,
                    ProviderDefinitionRecord.id == ProviderProbeRunRecord.provider_id,
                )
                .where(ProviderProbeRunRecord.id.in_(capability_ids))
            )
        }
        return [
            content_rows[record_id]
            if probe_type == "content"
            else capability_rows[record_id]
            for probe_type, record_id in selected
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

    def _recent_content_runs(self, per_source_limit: int) -> list[SourceProbeRunRecord]:
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
            .subquery()
        )
        return list(
            self._session.scalars(
                select(SourceProbeRunRecord)
                .join(ranked, SourceProbeRunRecord.id == ranked.c.record_id)
                .where(ranked.c.history_rank <= per_source_limit)
                .order_by(SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc())
            )
        )

    def _three_success_source_ids(self) -> list[str]:
        ranked = (
            select(
                SourceProbeRunRecord.source_id.label("source_id"),
                SourceProbeRunRecord.outcome.label("outcome"),
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
            .subquery()
        )
        return list(
            self._session.scalars(
                select(ranked.c.source_id)
                .where(ranked.c.history_rank <= 3)
                .group_by(ranked.c.source_id)
                .having(func.count() == 3)
                .having(
                    func.sum(case((ranked.c.outcome == "success", 1), else_=0)) == 3
                )
            )
        )

    def _latest_capability_runs(self) -> dict[str, ProviderProbeRunRecord]:
        ranked = (
            select(
                ProviderProbeRunRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=ProviderProbeRunRecord.provider_id,
                    order_by=(
                        ProviderProbeRunRecord.checked_at.desc(),
                        ProviderProbeRunRecord.id.desc(),
                    ),
                )
                .label("history_rank"),
            )
            .subquery()
        )
        records = self._session.scalars(
            select(ProviderProbeRunRecord)
            .join(ranked, ProviderProbeRunRecord.id == ranked.c.record_id)
            .where(ranked.c.history_rank == 1)
        )
        return {record.provider_id: record for record in records}

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
            suggested_status=run.suggested_status,
            suggested_status_label=(
                zh_label("status", run.suggested_status)
                if run.suggested_status
                else "未记录"
            ),
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
            suggested_status=run.availability,
            suggested_status_label=zh_label("availability", run.availability),
        )

    @staticmethod
    def _access_method_view(record: SourceAccessMethodRecord) -> AccessMethodView:
        return AccessMethodView(
            kind=record.kind,
            kind_label=zh_label("access_kind", record.kind),
            url=record.url,
            priority=record.priority,
            requires_manual_approval=record.requires_manual_approval,
            auth_envs=tuple(record.auth_envs or ([record.auth_env] if record.auth_env else [])),
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


# Public name for callers that only need the research read model.
ResearchQueryService = DashboardQueryService
