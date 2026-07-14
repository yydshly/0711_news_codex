from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    EntityRecord,
    EventCandidateRecord,
    EventModelRunRecord,
    EventRecord,
    EventScoreRecord,
    EventVersionRecord,
    FetchRunRecord,
    ModelUsageRecord,
    OperationRunRecord,
    ProviderDefinitionRecord,
    RawItemProcessingRecord,
    RawItemRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
    SourceProbeRunRecord,
    SourceRiskAssessmentRecord,
    WorkerRecord,
)
from newsradar.events.versions import EVENT_ALGORITHM_VERSIONS
from newsradar.ingestion.trial import TrialDecision, evaluate_trial_eligibility
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import AccessMethod, RiskAssessment, SourceDefinition
from newsradar.sources.yaml_loader import load_source_tree

_COMPLETED_FETCH_OUTCOMES = frozenset({"succeeded", "no_change"})
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVENT_QUALITY_WINDOW_HOURS = 72
EVENT_QUALITY_RELEVANCE_VERSION = EVENT_ALGORITHM_VERSIONS["relevance"]
EVENT_QUALITY_CLUSTER_VERSION = EVENT_ALGORITHM_VERSIONS["cluster"]


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    readable: bool
    provider_file_count: int
    provider_ids: frozenset[str]
    target_ids: frozenset[str]
    direct_target_ids: frozenset[str]
    ready_direct_target_ids: frozenset[str]
    indirect_target_ids: frozenset[str]
    catalog_only_target_ids: frozenset[str]

    @classmethod
    def unavailable(cls, _reason: str | None = None) -> CatalogSnapshot:
        return cls(
            False, 0, frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), frozenset()
        )


@dataclass(frozen=True, slots=True)
class CapabilityStage:
    label: str
    count: int
    detail: str
    href: str
    tone: str = "neutral"


@dataclass(frozen=True, slots=True)
class CapabilityPreviewItem:
    item_id: int
    source_id: str
    title: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class CapabilityEventPreview:
    event_id: int
    title: str
    status: str
    heat: float
    occurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class CapabilityGap:
    key: str
    title: str
    meaning: str
    href: str
    tone: str = "warning"


@dataclass(frozen=True, slots=True)
class EventQualityCoverageView:
    window_hours: int
    selected_count: int
    processed_count: int
    included_count: int
    excluded_count: int
    exclusion_reasons: tuple[tuple[str, int], ...]
    last_completed_at: datetime | None
    candidate_count: int
    current_event_count: int
    legacy_event_count: int
    model_fallback_count: int

    @property
    def reason_counts(self) -> tuple[tuple[str, int], ...]:
        return self.exclusion_reasons

    @property
    def last_completed(self) -> datetime | None:
        return self.last_completed_at


@dataclass(frozen=True, slots=True)
class CapabilityOverviewView:
    catalog_readable: bool
    provider_file_count: int
    provider_count: int
    target_count: int
    db_target_count: int
    direct_target_count: int
    ready_direct_target_count: int
    indirect_target_count: int
    catalog_only_target_count: int
    db_only_target_ids: tuple[str, ...]
    catalog_only_db_target_ids: tuple[str, ...]
    latest_probe_counts: tuple[tuple[str, int], ...]
    latest_probe_at: datetime | None
    trial_eligible_count: int
    fetched_source_count: int
    fetch_outcome_counts: tuple[tuple[str, int], ...]
    raw_item_count: int
    raw_source_count: int
    raw_first_at: datetime | None
    raw_latest_at: datetime | None
    recent_items: tuple[CapabilityPreviewItem, ...]
    event_count: int
    confirmed_event_count: int
    emerging_event_count: int
    recent_events: tuple[CapabilityEventPreview, ...]
    minimax_configured: bool
    model_usage_count: int
    event_model_run_count: int
    entity_count: int
    recent_worker_activity_count: int
    operation_status_counts: tuple[tuple[str, int], ...]
    stages: tuple[CapabilityStage, ...]
    gaps: tuple[CapabilityGap, ...]
    event_quality_coverage: EventQualityCoverageView = EventQualityCoverageView(
        window_hours=EVENT_QUALITY_WINDOW_HOURS,
        selected_count=0,
        processed_count=0,
        included_count=0,
        excluded_count=0,
        exclusion_reasons=(),
        last_completed_at=None,
        candidate_count=0,
        current_event_count=0,
        legacy_event_count=0,
        model_fallback_count=0,
    )


class EventQualityCoverageQueryService:
    """Aggregate the fixed v2 processing window without per-item queries."""

    WINDOW_HOURS = EVENT_QUALITY_WINDOW_HOURS
    RELEVANCE_ALGORITHM_VERSION = EVENT_QUALITY_RELEVANCE_VERSION
    CLUSTER_ALGORITHM_VERSION = EVENT_QUALITY_CLUSTER_VERSION

    def __init__(self, session: Session) -> None:
        self._session = session

    def build(self, *, now: datetime | None = None) -> EventQualityCoverageView:
        now = now or datetime.now(UTC)
        since = now - timedelta(hours=self.WINDOW_HOURS)
        item_time = func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)
        selected = select(RawItemRecord.id).where(
            item_time >= since,
            item_time <= now,
        )
        selected_count = int(
            self._session.scalar(
                select(func.count(RawItemRecord.id)).where(
                    item_time >= since,
                    item_time <= now,
                )
            )
            or 0
        )
        processing_rows = self._session.execute(
            select(RawItemProcessingRecord.outcome, RawItemProcessingRecord.reason_codes).where(
                RawItemProcessingRecord.raw_item_id.in_(selected),
                RawItemProcessingRecord.stage == "relevance",
                RawItemProcessingRecord.algorithm_version
                == self.RELEVANCE_ALGORITHM_VERSION,
                RawItemProcessingRecord.outcome.in_(("included", "excluded")),
            )
        ).all()
        outcomes = Counter(row.outcome for row in processing_rows)
        reasons: Counter[str] = Counter()
        for row in processing_rows:
            if row.outcome != "excluded" or not isinstance(row.reason_codes, list):
                continue
            reasons.update(str(reason) for reason in row.reason_codes)

        completed_rows = self._session.execute(
            select(OperationRunRecord.finished_at, OperationRunRecord.requested_scope)
            .where(
                OperationRunRecord.operation_type == "event_pipeline",
                OperationRunRecord.status == "succeeded",
                OperationRunRecord.finished_at >= since,
                OperationRunRecord.finished_at <= now,
            )
            .order_by(OperationRunRecord.finished_at.desc(), OperationRunRecord.id.desc())
        ).all()
        expected_versions = dict(EVENT_ALGORITHM_VERSIONS)
        last_completed_at = next(
            (
                row.finished_at
                for row in completed_rows
                if isinstance(row.requested_scope, dict)
                and row.requested_scope.get("window_hours") == self.WINDOW_HOURS
                and row.requested_scope.get("algorithm_versions") == expected_versions
            ),
            None,
        )
        if last_completed_at is not None and last_completed_at.tzinfo is None:
            last_completed_at = last_completed_at.replace(tzinfo=UTC)
        candidate_count = int(
            self._session.scalar(
                select(func.count(EventCandidateRecord.id)).where(
                    EventCandidateRecord.algorithm_version == self.CLUSTER_ALGORITHM_VERSION,
                    EventCandidateRecord.updated_at >= since,
                    EventCandidateRecord.updated_at <= now,
                )
            )
            or 0
        )
        visibility_counts = dict(
            self._session.execute(
                select(EventRecord.visibility, func.count(EventRecord.id))
                .where(
                    EventRecord.current_version_number > 0,
                    EventRecord.updated_at >= since,
                    EventRecord.updated_at <= now,
                )
                .group_by(EventRecord.visibility)
            ).all()
        )
        model_fallback_count = int(
            self._session.scalar(
                select(func.count(EventModelRunRecord.id))
                .join(ModelUsageRecord, ModelUsageRecord.id == EventModelRunRecord.model_usage_id)
                .where(
                    EventModelRunRecord.created_at >= since,
                    EventModelRunRecord.created_at <= now,
                    ModelUsageRecord.outcome != "success",
                )
            )
            or 0
        )
        return EventQualityCoverageView(
            window_hours=self.WINDOW_HOURS,
            selected_count=selected_count,
            processed_count=len(processing_rows),
            included_count=outcomes["included"],
            excluded_count=outcomes["excluded"],
            exclusion_reasons=tuple(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
            last_completed_at=last_completed_at,
            candidate_count=candidate_count,
            current_event_count=int(visibility_counts.get("current", 0)),
            legacy_event_count=int(visibility_counts.get("legacy", 0)),
            model_fallback_count=model_fallback_count,
        )


def load_catalog_snapshot(
    provider_root: Path | None = None,
    source_root: Path | None = None,
) -> CatalogSnapshot:
    """Load the reviewed YAML catalog without mutating it or contacting the network."""
    provider_root = provider_root or _PROJECT_ROOT / "providers"
    source_root = source_root or _PROJECT_ROOT / "sources"
    if not provider_root.is_dir() or not source_root.is_dir():
        return CatalogSnapshot.unavailable()
    try:
        providers = load_provider_tree(provider_root)
        sources = load_source_tree(source_root)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return CatalogSnapshot.unavailable()
    if not providers or not sources:
        return CatalogSnapshot.unavailable()
    provider_ids = {provider.id for provider in providers}
    provider_ids.update(source.provider_id for source in sources)
    return CatalogSnapshot(
        readable=True,
        provider_file_count=len(providers),
        provider_ids=frozenset(provider_ids),
        target_ids=frozenset(source.id for source in sources),
        direct_target_ids=frozenset(
            source.id for source in sources if source.coverage_mode.value == "direct"
        ),
        ready_direct_target_ids=frozenset(
            source.id
            for source in sources
            if source.coverage_mode.value == "direct" and source.availability.value == "ready"
        ),
        indirect_target_ids=frozenset(
            source.id for source in sources if source.coverage_mode.value == "indirect"
        ),
        catalog_only_target_ids=frozenset(
            source.id for source in sources if source.coverage_mode.value == "catalog_only"
        ),
    )


class CapabilityQueryService:
    """Build a bounded, read-only projection of the project's actual capability."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def build(
        self,
        catalog: CatalogSnapshot,
        *,
        minimax_configured: bool,
        now: datetime | None = None,
    ) -> CapabilityOverviewView:
        now = now or datetime.now(UTC)
        db_sources = list(self._session.scalars(select(SourceDefinitionRecord)))
        db_ids = {source.id for source in db_sources}
        current_ids = set(catalog.target_ids) if catalog.readable else db_ids
        current_sources = [source for source in db_sources if source.id in current_ids]

        latest_probes = self._latest_probes(current_ids)
        probe_counts = Counter(run.outcome for run in latest_probes.values())
        probe_counts["unprobed"] = max(len(current_ids) - len(latest_probes), 0)
        probe_counts = +probe_counts
        latest_probe_at = max((run.finished_at for run in latest_probes.values()), default=None)

        trial_decisions = self._trial_decisions(current_sources)
        trial_eligible_count = sum(decision.eligible for decision in trial_decisions.values())

        fetch_counts: Counter[str] = Counter()
        fetched_ids: set[str] = set()
        if current_ids:
            fetch_counts.update(
                {
                    outcome: int(count)
                    for outcome, count in self._session.execute(
                        select(FetchRunRecord.outcome, func.count(FetchRunRecord.id))
                        .where(FetchRunRecord.source_id.in_(current_ids))
                        .group_by(FetchRunRecord.outcome)
                    )
                }
            )
            fetched_ids.update(
                self._session.scalars(
                    select(FetchRunRecord.source_id)
                    .where(
                        FetchRunRecord.source_id.in_(current_ids),
                        FetchRunRecord.outcome.in_(_COMPLETED_FETCH_OUTCOMES),
                    )
                    .distinct()
                )
            )

        raw_filter = RawItemRecord.source_id.in_(current_ids)
        raw_item_count = (
            int(self._session.scalar(select(func.count(RawItemRecord.id)).where(raw_filter)) or 0)
            if current_ids
            else 0
        )
        raw_source_count = (
            int(
                self._session.scalar(
                    select(func.count(func.distinct(RawItemRecord.source_id))).where(raw_filter)
                )
                or 0
            )
            if current_ids
            else 0
        )
        raw_first_at, raw_latest_at = (None, None)
        recent_raw: list[RawItemRecord] = []
        if current_ids:
            raw_first_at, raw_latest_at = self._session.execute(
                select(
                    func.min(func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)),
                    func.max(func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)),
                ).where(raw_filter)
            ).one()
            recent_raw = list(
                self._session.scalars(
                    select(RawItemRecord)
                    .where(raw_filter)
                    .order_by(
                        func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at).desc(),
                        RawItemRecord.id.desc(),
                    )
                    .limit(5)
                )
            )

        event_count = int(self._session.scalar(select(func.count(EventRecord.id))) or 0)
        confirmed_event_count = int(
            self._session.scalar(
                select(func.count(EventRecord.id)).where(EventRecord.status == "confirmed")
            )
            or 0
        )
        emerging_event_count = int(
            self._session.scalar(
                select(func.count(EventRecord.id)).where(EventRecord.status == "emerging")
            )
            or 0
        )
        event_rows = self._session.execute(
            select(
                EventRecord.id,
                EventRecord.status,
                EventRecord.occurred_at,
                EventVersionRecord.zh_title,
                func.coalesce(EventScoreRecord.heat, 0.0).label("heat"),
            )
            .join(
                EventVersionRecord,
                and_(
                    EventVersionRecord.event_id == EventRecord.id,
                    EventVersionRecord.version_number == EventRecord.current_version_number,
                ),
            )
            .outerjoin(
                EventScoreRecord,
                and_(
                    EventScoreRecord.event_id == EventRecord.id,
                    EventScoreRecord.version_number == EventRecord.current_version_number,
                ),
            )
            .where(EventRecord.current_version_number > 0)
            .order_by(
                func.coalesce(EventScoreRecord.heat, 0.0).desc(),
                EventRecord.occurred_at.desc(),
                EventRecord.id,
            )
            .limit(5)
        ).all()

        model_usage_count = int(self._session.scalar(select(func.count(ModelUsageRecord.id))) or 0)
        event_model_run_count = int(
            self._session.scalar(select(func.count(EventModelRunRecord.id))) or 0
        )
        entity_count = int(self._session.scalar(select(func.count(EntityRecord.id))) or 0)
        recent_worker_activity_count = int(
            self._session.scalar(
                select(func.count(WorkerRecord.worker_id)).where(
                    WorkerRecord.last_heartbeat_at >= now - timedelta(minutes=5)
                )
            )
            or 0
        )
        operation_counts = tuple(
            (status, int(count))
            for status, count in self._session.execute(
                select(OperationRunRecord.status, func.count(OperationRunRecord.id))
                .group_by(OperationRunRecord.status)
                .order_by(OperationRunRecord.status)
            )
        )

        provider_count = (
            len(catalog.provider_ids)
            if catalog.readable
            else int(self._session.scalar(select(func.count(ProviderDefinitionRecord.id))) or 0)
        )
        target_count = len(current_ids)
        direct_count = (
            len(catalog.direct_target_ids)
            if catalog.readable
            else sum(source.coverage_mode == "direct" for source in current_sources)
        )
        ready_direct_count = (
            len(catalog.ready_direct_target_ids)
            if catalog.readable
            else sum(
                source.coverage_mode == "direct" and source.availability == "ready"
                for source in current_sources
            )
        )
        indirect_count = (
            len(catalog.indirect_target_ids)
            if catalog.readable
            else sum(source.coverage_mode == "indirect" for source in current_sources)
        )
        catalog_only_count = (
            len(catalog.catalog_only_target_ids)
            if catalog.readable
            else sum(source.coverage_mode == "catalog_only" for source in current_sources)
        )
        ready_direct_ids = (
            set(catalog.ready_direct_target_ids)
            if catalog.readable
            else {
                source.id
                for source in current_sources
                if source.coverage_mode == "direct" and source.availability == "ready"
            }
        )
        ready_direct_fetched_count = len(ready_direct_ids & fetched_ids)

        gaps = self._gaps(
            catalog=catalog,
            db_only=sorted(db_ids - current_ids),
            missing_in_db=sorted(current_ids - db_ids),
            ready_direct_count=ready_direct_count,
            ready_direct_fetched_count=ready_direct_fetched_count,
            minimax_configured=minimax_configured,
            model_usage_count=model_usage_count,
            entity_count=entity_count,
            operation_counts=dict(operation_counts),
        )
        stages = (
            CapabilityStage("平台目录", provider_count, "已登记的平台或服务", "/providers"),
            CapabilityStage("具体目标", target_count, "账号、频道、仓库、订阅源或查询", "/targets"),
            CapabilityStage(
                "探测成功",
                probe_counts.get("success", 0),
                "最新一次获得合格样本",
                "/probes?outcome=success",
            ),
            CapabilityStage(
                "可试用",
                trial_eligible_count,
                "符合当前公开直连规则",
                "/targets",
            ),
            CapabilityStage(
                "实际抓取来源", len(fetched_ids), "至少完成一次真实抓取", "/fetch-runs"
            ),
            CapabilityStage("RawItem", raw_item_count, "规范化原始信息", "/items"),
            CapabilityStage("事件", event_count, "由原始信息聚合出的线索", "/events"),
            CapabilityStage(
                "MiniMax 增强",
                event_model_run_count,
                "已记录的事件模型处理",
                "/system",
                "success" if event_model_run_count else "warning",
            ),
        )
        return CapabilityOverviewView(
            catalog_readable=catalog.readable,
            provider_file_count=catalog.provider_file_count,
            provider_count=provider_count,
            target_count=target_count,
            db_target_count=len(db_ids),
            direct_target_count=direct_count,
            ready_direct_target_count=ready_direct_count,
            indirect_target_count=indirect_count,
            catalog_only_target_count=catalog_only_count,
            db_only_target_ids=tuple(sorted(db_ids - current_ids)),
            catalog_only_db_target_ids=tuple(sorted(current_ids - db_ids)),
            latest_probe_counts=tuple(sorted(probe_counts.items())),
            latest_probe_at=latest_probe_at,
            trial_eligible_count=trial_eligible_count,
            fetched_source_count=len(fetched_ids),
            fetch_outcome_counts=tuple(sorted(fetch_counts.items())),
            raw_item_count=raw_item_count,
            raw_source_count=raw_source_count,
            raw_first_at=raw_first_at,
            raw_latest_at=raw_latest_at,
            recent_items=tuple(
                CapabilityPreviewItem(
                    item_id=item.id,
                    source_id=item.source_id,
                    title=item.title or "未命名原始条目",
                    published_at=item.published_at or item.fetched_at,
                )
                for item in recent_raw
            ),
            event_count=event_count,
            confirmed_event_count=confirmed_event_count,
            emerging_event_count=emerging_event_count,
            recent_events=tuple(
                CapabilityEventPreview(
                    event_id=event.id,
                    title=event.zh_title or "未命名事件",
                    status=event.status,
                    heat=float(event.heat),
                    occurred_at=event.occurred_at,
                )
                for event in event_rows
            ),
            minimax_configured=minimax_configured,
            model_usage_count=model_usage_count,
            event_model_run_count=event_model_run_count,
            entity_count=entity_count,
            recent_worker_activity_count=recent_worker_activity_count,
            operation_status_counts=operation_counts,
            stages=stages,
            gaps=gaps,
            event_quality_coverage=EventQualityCoverageQueryService(self._session).build(now=now),
        )

    def _latest_probes(self, source_ids: set[str]) -> dict[str, SourceProbeRunRecord]:
        if not source_ids:
            return {}
        ranked = (
            select(
                SourceProbeRunRecord.id.label("probe_id"),
                func.row_number()
                .over(
                    partition_by=SourceProbeRunRecord.source_id,
                    order_by=(
                        SourceProbeRunRecord.finished_at.desc(),
                        SourceProbeRunRecord.id.desc(),
                    ),
                )
                .label("rank"),
            )
            .where(SourceProbeRunRecord.source_id.in_(source_ids))
            .subquery()
        )
        rows = self._session.scalars(
            select(SourceProbeRunRecord)
            .join(ranked, ranked.c.probe_id == SourceProbeRunRecord.id)
            .where(ranked.c.rank == 1)
        )
        return {row.source_id: row for row in rows}

    def _trial_decisions(self, sources: list[SourceDefinitionRecord]) -> dict[str, TrialDecision]:
        if not sources:
            return {}
        ids = [source.id for source in sources]
        methods: dict[str, list[SourceAccessMethodRecord]] = defaultdict(list)
        for method in self._session.scalars(
            select(SourceAccessMethodRecord).where(SourceAccessMethodRecord.source_id.in_(ids))
        ):
            methods[method.source_id].append(method)
        ranked_risks = (
            select(
                SourceRiskAssessmentRecord.id.label("risk_id"),
                func.row_number()
                .over(
                    partition_by=SourceRiskAssessmentRecord.source_id,
                    order_by=(
                        SourceRiskAssessmentRecord.assessed_at.desc(),
                        SourceRiskAssessmentRecord.id.desc(),
                    ),
                )
                .label("rank"),
            )
            .where(SourceRiskAssessmentRecord.source_id.in_(ids))
            .subquery()
        )
        risks = {
            risk.source_id: risk
            for risk in self._session.scalars(
                select(SourceRiskAssessmentRecord)
                .join(ranked_risks, ranked_risks.c.risk_id == SourceRiskAssessmentRecord.id)
                .where(ranked_risks.c.rank == 1)
            )
        }
        snapshots = SourceRepository(self._session).latest_probe_snapshots(ids)
        return {
            source.id: evaluate_trial_eligibility(
                SourceDefinition.model_construct(
                    coverage_mode=source.coverage_mode,
                    availability=source.availability,
                    access_methods=[
                        AccessMethod.model_construct(
                            kind=method.kind,
                            requires_manual_approval=method.requires_manual_approval,
                            auth_envs=tuple(
                                method.auth_envs or ([method.auth_env] if method.auth_env else [])
                            ),
                        )
                        for method in methods.get(source.id, [])
                    ],
                    risk=RiskAssessment.model_construct(
                        hard_block_reason=(
                            risks[source.id].hard_block_reason if source.id in risks else None
                        )
                    ),
                ),
                snapshots.get(source.id),
            )
            for source in sources
        }

    @staticmethod
    def _gaps(
        *,
        catalog: CatalogSnapshot,
        db_only: list[str],
        missing_in_db: list[str],
        ready_direct_count: int,
        ready_direct_fetched_count: int,
        minimax_configured: bool,
        model_usage_count: int,
        entity_count: int,
        operation_counts: dict[str, int],
    ) -> tuple[CapabilityGap, ...]:
        gaps: list[CapabilityGap] = []
        if not catalog.readable:
            gaps.append(
                CapabilityGap(
                    "catalog_unreadable",
                    "来源目录暂时不可读取",
                    "当前数字回退为数据库快照，不能确认 YAML 目录真相。",
                    "/system",
                    "failed",
                )
            )
        if db_only or missing_in_db:
            gaps.append(
                CapabilityGap(
                    "catalog_drift",
                    "YAML 与数据库存在目录漂移",
                    f"数据库额外 {len(db_only)} 项，尚未同步 {len(missing_in_db)} 项。",
                    "/targets",
                )
            )
        if ready_direct_fetched_count < ready_direct_count:
            gaps.append(
                CapabilityGap(
                    "fetch_coverage",
                    "就绪目标尚未全部完成真实抓取",
                    f"{ready_direct_count} 个就绪直连目标中，"
                    f"{ready_direct_fetched_count} 个完成过真实抓取。",
                    "/fetch-runs",
                )
            )
        if not minimax_configured:
            gaps.append(
                CapabilityGap(
                    "minimax_not_configured",
                    "MiniMax 当前未配置",
                    "规则流程仍可运行，但不会产生模型增强结果。",
                    "/system",
                )
            )
        elif model_usage_count == 0:
            gaps.append(
                CapabilityGap(
                    "minimax_unused",
                    "MiniMax 已配置但尚无调用记录",
                    "配置存在不代表模型已经参与事件处理。",
                    "/system",
                )
            )
        if entity_count == 0:
            gaps.append(
                CapabilityGap(
                    "entities_missing",
                    "尚未产出实体数据",
                    "当前事件还不能按公司、人物或技术实体下钻。",
                    "/events",
                )
            )
        failures = operation_counts.get("failed", 0) + operation_counts.get("partial", 0)
        if failures:
            gaps.append(
                CapabilityGap(
                    "operation_failures",
                    "存在失败或部分成功的历史操作",
                    f"共 {failures} 个操作需要在运行记录中定位。",
                    "/operations",
                )
            )
        return tuple(gaps)
