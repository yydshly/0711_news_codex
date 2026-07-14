from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsradar.db.models import (
    FetchRunRecord,
    RawItemRecord,
    SourceAccessMethodRecord,
    SourceDefinitionRecord,
)
from newsradar.sources.mixed_wave import MIXED_WAVE_GROUPS, MIXED_WAVE_SOURCE_IDS

_STABLE_OUTCOMES = frozenset({"succeeded", "no_change"})
_GROUP_LABELS = {
    "reddit": "Reddit 社区",
    "youtube": "YouTube 视频",
    "bluesky": "Bluesky 社交",
    "mastodon": "Mastodon 主题",
    "hackernews": "Hacker News",
    "techmeme": "Techmeme",
    "gdelt": "GDELT",
    "google_news": "Google News",
    "professional_media": "专业媒体",
}


class MixedSourceState(StrEnum):
    DIRECT_READY = "direct_ready"
    INDIRECT_READY = "indirect_ready"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    FAILED = "failed"
    NOT_RUN = "not_run"


_STATE_LABELS = {
    MixedSourceState.DIRECT_READY: "直接抓取",
    MixedSourceState.INDIRECT_READY: "间接发现",
    MixedSourceState.BLOCKED: "等待凭据或权限",
    MixedSourceState.DEGRADED: "降级运行",
    MixedSourceState.FAILED: "抓取失败",
    MixedSourceState.NOT_RUN: "尚未运行",
}


@dataclass(frozen=True, slots=True)
class MixedSourceRun:
    outcome: str
    finished_at: datetime | None
    item_count: int
    error_code: str | None


@dataclass(frozen=True, slots=True)
class MixedSourceTarget:
    source_id: str
    name: str
    group: str
    provider_id: str
    coverage_mode: str
    availability: str
    state: str
    state_label: str
    roles: tuple[str, ...]
    access_kind: str | None
    access_url: str | None
    recent_runs: tuple[MixedSourceRun, ...]
    three_run_outcomes: tuple[str, ...]
    three_run_stable: bool
    raw_item_count: int
    latest_content_at: datetime | None
    latest_error_code: str | None
    conclusion_zh: str
    next_action_zh: str


@dataclass(frozen=True, slots=True)
class MixedSourceGroup:
    key: str
    label: str
    targets: tuple[MixedSourceTarget, ...]


@dataclass(frozen=True, slots=True)
class MixedSourceSummary:
    catalog_target_count: int
    synced_target_count: int
    direct_ready_count: int
    indirect_ready_count: int
    blocked_count: int
    degraded_count: int
    failed_count: int
    not_run_count: int
    three_run_stable_count: int


@dataclass(frozen=True, slots=True)
class MixedSourceDashboard:
    summary: MixedSourceSummary
    groups: tuple[MixedSourceGroup, ...]

    @property
    def targets(self) -> tuple[MixedSourceTarget, ...]:
        return tuple(target for group in self.groups for target in group.targets)


class MixedSourceQueryService:
    """Read-only projection of the named mixed-source cohort and its real runtime evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def build(self) -> MixedSourceDashboard:
        sources = {
            source.id: source
            for source in self._session.scalars(
                select(SourceDefinitionRecord).where(
                    SourceDefinitionRecord.id.in_(MIXED_WAVE_SOURCE_IDS)
                )
            )
        }
        methods = self._primary_methods(set(sources))
        runs = self._recent_runs(set(sources))
        raw_counts = self._raw_counts(set(sources))

        groups: list[MixedSourceGroup] = []
        states: Counter[str] = Counter()
        stable_count = 0
        for group_key, source_ids in MIXED_WAVE_GROUPS.items():
            targets = tuple(
                self._target(
                    group_key,
                    sources[source_id],
                    methods.get(source_id),
                    runs.get(source_id, ()),
                    raw_counts.get(source_id, (0, None)),
                )
                for source_id in source_ids
                if source_id in sources
            )
            states.update(target.state for target in targets)
            stable_count += sum(target.three_run_stable for target in targets)
            groups.append(
                MixedSourceGroup(
                    key=group_key,
                    label=_GROUP_LABELS[group_key],
                    targets=targets,
                )
            )

        return MixedSourceDashboard(
            summary=MixedSourceSummary(
                catalog_target_count=len(MIXED_WAVE_SOURCE_IDS),
                synced_target_count=len(sources),
                direct_ready_count=states[MixedSourceState.DIRECT_READY],
                indirect_ready_count=states[MixedSourceState.INDIRECT_READY],
                blocked_count=states[MixedSourceState.BLOCKED],
                degraded_count=states[MixedSourceState.DEGRADED],
                failed_count=states[MixedSourceState.FAILED],
                not_run_count=states[MixedSourceState.NOT_RUN],
                three_run_stable_count=stable_count,
            ),
            groups=tuple(groups),
        )

    def _primary_methods(self, source_ids: set[str]) -> dict[str, SourceAccessMethodRecord]:
        if not source_ids:
            return {}
        rows = self._session.scalars(
            select(SourceAccessMethodRecord)
            .where(SourceAccessMethodRecord.source_id.in_(source_ids))
            .order_by(SourceAccessMethodRecord.source_id, SourceAccessMethodRecord.priority)
        )
        methods: dict[str, SourceAccessMethodRecord] = {}
        for row in rows:
            methods.setdefault(row.source_id, row)
        return methods

    def _recent_runs(self, source_ids: set[str]) -> dict[str, tuple[FetchRunRecord, ...]]:
        if not source_ids:
            return {}
        ranked = (
            select(
                FetchRunRecord.id.label("run_id"),
                func.row_number()
                .over(
                    partition_by=FetchRunRecord.source_id,
                    order_by=(FetchRunRecord.finished_at.desc(), FetchRunRecord.id.desc()),
                )
                .label("history_rank"),
            )
            .where(
                FetchRunRecord.source_id.in_(source_ids),
                FetchRunRecord.finished_at.is_not(None),
            )
            .subquery()
        )
        rows = self._session.scalars(
            select(FetchRunRecord)
            .join(ranked, ranked.c.run_id == FetchRunRecord.id)
            .where(ranked.c.history_rank <= 3)
            .order_by(
                FetchRunRecord.source_id,
                FetchRunRecord.finished_at.desc(),
                FetchRunRecord.id.desc(),
            )
        )
        by_source: dict[str, list[FetchRunRecord]] = defaultdict(list)
        for row in rows:
            by_source[row.source_id].append(row)
        return {source_id: tuple(values) for source_id, values in by_source.items()}

    def _raw_counts(self, source_ids: set[str]) -> dict[str, tuple[int, datetime | None]]:
        if not source_ids:
            return {}
        return {
            source_id: (int(count), _aware(latest))
            for source_id, count, latest in self._session.execute(
                select(
                    RawItemRecord.source_id,
                    func.count(RawItemRecord.id),
                    func.max(func.coalesce(RawItemRecord.published_at, RawItemRecord.fetched_at)),
                )
                .where(RawItemRecord.source_id.in_(source_ids))
                .group_by(RawItemRecord.source_id)
            )
        }

    @staticmethod
    def _target(
        group: str,
        source: SourceDefinitionRecord,
        method: SourceAccessMethodRecord | None,
        runs: tuple[FetchRunRecord, ...],
        raw: tuple[int, datetime | None],
    ) -> MixedSourceTarget:
        latest = runs[0] if runs else None
        run_views = tuple(
            MixedSourceRun(
                outcome=run.outcome,
                finished_at=_aware(run.finished_at),
                item_count=int(run.item_count or 0),
                error_code=run.error_code,
            )
            for run in runs
        )
        outcomes = tuple(run.outcome for run in runs)
        stable = len(outcomes) == 3 and all(value in _STABLE_OUTCOMES for value in outcomes)
        state = _classify(source, latest, three_run_stable=stable)
        conclusion, next_action = _explain(state, source, latest)
        return MixedSourceTarget(
            source_id=source.id,
            name=source.name,
            group=group,
            provider_id=source.provider_id,
            coverage_mode=source.coverage_mode,
            availability=source.availability,
            state=state.value,
            state_label=_STATE_LABELS[state],
            roles=tuple(source.roles or ()),
            access_kind=method.kind if method else None,
            access_url=method.url if method else None,
            recent_runs=run_views,
            three_run_outcomes=outcomes,
            three_run_stable=stable,
            raw_item_count=raw[0],
            latest_content_at=raw[1],
            latest_error_code=latest.error_code if latest else None,
            conclusion_zh=conclusion,
            next_action_zh=next_action,
        )


def _classify(
    source: SourceDefinitionRecord,
    latest: FetchRunRecord | None,
    *,
    three_run_stable: bool,
) -> MixedSourceState:
    if latest and latest.outcome == "blocked":
        return MixedSourceState.BLOCKED
    if latest and latest.outcome == "partial":
        return MixedSourceState.DEGRADED
    if latest and latest.outcome == "failed":
        return MixedSourceState.FAILED
    if latest and latest.outcome in _STABLE_OUTCOMES:
        if source.status == "degraded" and not three_run_stable:
            return MixedSourceState.DEGRADED
        return (
            MixedSourceState.INDIRECT_READY
            if source.coverage_mode == "indirect"
            else MixedSourceState.DIRECT_READY
        )
    if source.availability != "ready":
        return MixedSourceState.BLOCKED
    if source.status == "degraded":
        return MixedSourceState.DEGRADED
    return MixedSourceState.NOT_RUN


def _explain(
    state: MixedSourceState,
    source: SourceDefinitionRecord,
    latest: FetchRunRecord | None,
) -> tuple[str, str]:
    if state is MixedSourceState.DIRECT_READY:
        return "已从登记入口直接获得内容。", "继续观察最近三轮稳定性。"
    if state is MixedSourceState.INDIRECT_READY:
        return "已通过聚合入口发现原始媒体报道。", "回到原始媒体页面确认事实与归属。"
    if state is MixedSourceState.BLOCKED:
        return (
            "接口已登记，但当前缺少凭据、审批或访问条件。",
            "按来源详情配置凭据；不得回退登录网页抓取。",
        )
    if state is MixedSourceState.DEGRADED:
        return "入口可访问，但最近结果或来源状态处于降级。", "检查字段漂移、限流或超时后重新验证。"
    if state is MixedSourceState.FAILED:
        code = latest.error_code if latest and latest.error_code else "unknown"
        return f"最近一次真实抓取失败（{code}）。", "查看抓取记录并按有限重试策略处理。"
    return "目录已登记，但尚无真实抓取记录。", "排队一次受控抓取以确认内容能力。"


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
