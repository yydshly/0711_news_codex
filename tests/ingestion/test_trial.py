import math
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from newsradar.db.models import Base
from newsradar.ingestion.trial import (
    ProbeSnapshot,
    TrialDecision,
    evaluate_trial_eligibility,
)
from newsradar.sources.probes.base import ProbeOutcome, ProbeResult, ProbeSample
from newsradar.sources.repository import SourceRepository
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source


def _source(**changes: object) -> SourceDefinition:
    data = valid_source()
    data.update(changes)
    return SourceDefinition.model_validate(data)


def _successful_probe(**changes: object) -> ProbeSnapshot:
    values: dict[str, object] = {
        "outcome": "success",
        "sample_count": 1,
        "field_completeness": 1.0,
        "sample_fields": frozenset({"title", "canonical_url"}),
        "finished_at": datetime(2026, 7, 13, tzinfo=UTC),
    }
    values.update(changes)
    return ProbeSnapshot(**values)


def test_direct_ready_successful_probe_is_trial_eligible() -> None:
    decision = evaluate_trial_eligibility(_source(), _successful_probe())

    assert decision.eligible is True
    assert decision.code is None
    assert decision.reason == "可试用抓取：公开直连且首次探测合格"


@pytest.mark.parametrize("completeness", [math.nan, math.inf, -math.inf, -0.01, 1.01])
def test_trial_rejects_non_finite_or_out_of_range_completeness(completeness: float) -> None:
    decision = evaluate_trial_eligibility(
        _source(), _successful_probe(field_completeness=completeness)
    )

    assert decision.eligible is False
    assert decision.code == "invalid_field_completeness"
    assert decision.reason == "不可试用抓取：样本字段完整度必须是 0 到 1 之间的有限值。"


def test_credentials_access_method_is_not_trial_eligible() -> None:
    source = _source(
        access_methods=[
            {
                "kind": "rss",
                "url": "https://www.anthropic.com/news/rss.xml",
                "priority": 1,
                "auth_envs": ["TRIAL_TEST_TOKEN"],
            }
        ]
    )

    decision = evaluate_trial_eligibility(source, _successful_probe())

    assert decision == TrialDecision(
        False,
        "credentials_not_allowed",
        "试用抓取不使用凭据访问方式。",
    )


def test_indirect_source_is_discovery_only() -> None:
    decision = evaluate_trial_eligibility(_source(coverage_mode="indirect"), _successful_probe())

    assert decision == TrialDecision(False, "discovery_only", "仅用于发现，需回源确认")


def test_catalog_only_source_has_a_distinct_reason() -> None:
    decision = evaluate_trial_eligibility(
        _source(coverage_mode="catalog_only"), _successful_probe()
    )

    assert decision == TrialDecision(False, "catalog_only", "仅目录收录，不提供试用抓取。")


@pytest.mark.parametrize(
    ("source", "probe", "expected"),
    [
        (
            _source(),
            None,
            TrialDecision(False, "no_probe", "不可试用抓取：尚无完成的探测记录。"),
        ),
        (
            _source(availability="requires_credentials"),
            _successful_probe(),
            TrialDecision(False, "not_ready", "不可试用抓取：来源当前未就绪。"),
        ),
        (
            _source(
                risk={
                    "terms": 1,
                    "authentication": 0,
                    "stability": 2,
                    "data_quality": 1,
                    "operating_cost": 0,
                    "hard_block_reason": "terms prohibit automation",
                }
            ),
            _successful_probe(),
            TrialDecision(
                False,
                "hard_blocked",
                "不可试用抓取：来源存在条款或合规硬性阻塞。",
            ),
        ),
        (
            _source(
                access_methods=[
                    {
                        "kind": "html",
                        "url": "https://www.anthropic.com/news",
                        "priority": 1,
                        "requires_manual_approval": True,
                    }
                ]
            ),
            _successful_probe(),
            TrialDecision(
                False,
                "no_automatic_method",
                "不可试用抓取：没有非 HTML 自动访问方式。",
            ),
        ),
        (
            _source(),
            _successful_probe(outcome="failed"),
            TrialDecision(False, "probe_not_successful", "不可试用抓取：最新探测未成功。"),
        ),
        (
            _source(),
            _successful_probe(sample_count=0),
            TrialDecision(False, "no_samples", "不可试用抓取：最新探测未获得样本。"),
        ),
        (
            _source(),
            _successful_probe(sample_count=-1),
            TrialDecision(False, "no_samples", "不可试用抓取：最新探测未获得样本。"),
        ),
        (
            _source(),
            _successful_probe(field_completeness=0.59),
            TrialDecision(
                False,
                "incomplete_fields",
                "不可试用抓取：样本字段完整度低于 0.60。",
            ),
        ),
        (
            _source(),
            _successful_probe(sample_fields=frozenset({"title"})),
            TrialDecision(
                False,
                "missing_required_fields",
                "不可试用抓取：样本缺少 title 或 canonical_url。",
            ),
        ),
    ],
)
def test_ineligible_trial_conditions_have_stable_decisions(
    source: SourceDefinition,
    probe: ProbeSnapshot | None,
    expected: TrialDecision,
) -> None:
    decision = evaluate_trial_eligibility(source, probe)

    assert decision == expected


def test_repository_reads_the_latest_probe_snapshot() -> None:
    source = _source()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = SourceRepository(session)
        repository.sync([source])
        assert repository.latest_probe_snapshot(source.id) is None

        finished_at = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://www.anthropic.com/news/rss.xml",
                outcome=ProbeOutcome.SUCCESS,
                started_at=finished_at,
                finished_at=finished_at,
                sample_count=1,
                field_completeness=1.0,
                samples=[
                    ProbeSample(
                        external_id="1",
                        title="Release",
                        canonical_url="https://www.anthropic.com/news/release",
                    )
                ],
                suggested_status="candidate",
                reason="ok",
            )
        )

        snapshot = repository.latest_probe_snapshot(source.id)
        assert snapshot is not None
        assert snapshot.outcome == "success"
        assert snapshot.sample_count == 1
        assert snapshot.field_completeness == 1.0
        assert snapshot.sample_fields == frozenset({"title", "canonical_url"})
        assert snapshot.finished_at == finished_at.replace(tzinfo=None)


def test_repository_uses_the_latest_completed_probe_and_unions_sample_fields() -> None:
    source = _source()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = SourceRepository(session)
        repository.sync([source])
        assert repository.latest_probe_snapshot(source.id) is None

        earlier = datetime(2026, 7, 12, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://www.anthropic.com/news/rss.xml",
                outcome=ProbeOutcome.FAILED,
                started_at=earlier,
                finished_at=earlier,
                sample_count=0,
                field_completeness=0.0,
                suggested_status="candidate",
                reason="failed",
            )
        )
        later = datetime(2026, 7, 13, tzinfo=UTC)
        repository.save_probe_result(
            ProbeResult(
                source_id=source.id,
                access_kind="rss",
                access_url="https://www.anthropic.com/news/rss.xml",
                outcome=ProbeOutcome.SUCCESS,
                started_at=later,
                finished_at=later,
                sample_count=2,
                field_completeness=1.0,
                samples=[
                    ProbeSample(external_id="one", title="First"),
                    ProbeSample(
                        external_id="two",
                        canonical_url="https://www.anthropic.com/news/second",
                    ),
                ],
                suggested_status="candidate",
                reason="ok",
            )
        )

        snapshot = repository.latest_probe_snapshot(source.id)
        assert snapshot is not None
        assert snapshot.outcome == "success"
        assert snapshot.sample_count == 2
        assert snapshot.sample_fields == frozenset({"title", "canonical_url"})
        assert evaluate_trial_eligibility(source, snapshot).eligible is True


def test_repository_reads_latest_completed_snapshots_for_multiple_sources() -> None:
    first = _source()
    second = _source(id="anthropic-news-two")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = SourceRepository(session)
        repository.sync([first, second])
        earlier = datetime(2026, 7, 12, tzinfo=UTC)
        later = datetime(2026, 7, 13, tzinfo=UTC)
        for source in (first, second):
            repository.save_probe_result(
                ProbeResult(
                    source_id=source.id,
                    access_kind="rss",
                    access_url="https://www.anthropic.com/news/rss.xml",
                    outcome=ProbeOutcome.FAILED,
                    started_at=earlier,
                    finished_at=earlier,
                    sample_count=0,
                    field_completeness=0.0,
                    suggested_status="candidate",
                    reason="failed",
                )
            )
        repository.save_probe_result(
            ProbeResult(
                source_id=first.id,
                access_kind="rss",
                access_url="https://www.anthropic.com/news/rss.xml",
                outcome=ProbeOutcome.SUCCESS,
                started_at=later,
                finished_at=later,
                sample_count=2,
                field_completeness=1.0,
                samples=[
                    ProbeSample(external_id="one", title="First"),
                    ProbeSample(
                        external_id="two",
                        canonical_url="https://www.anthropic.com/news/second",
                    ),
                ],
                suggested_status="candidate",
                reason="ok",
            )
        )
        repository.save_probe_result(
            ProbeResult(
                source_id=second.id,
                access_kind="rss",
                access_url="https://www.anthropic.com/news/rss.xml",
                outcome=ProbeOutcome.SUCCESS,
                started_at=later,
                finished_at=later,
                sample_count=1,
                field_completeness=1.0,
                samples=[
                    ProbeSample(
                        external_id="three",
                        title="Second source",
                        canonical_url="https://www.anthropic.com/news/third",
                    )
                ],
                suggested_status="candidate",
                reason="ok",
            )
        )

        snapshots = repository.latest_probe_snapshots([first.id, second.id, "unknown"])

    assert set(snapshots) == {first.id, second.id}
    assert snapshots[first.id].outcome == snapshots[second.id].outcome == "success"
    assert snapshots[first.id].sample_fields == frozenset({"title", "canonical_url"})
    assert snapshots[second.id].sample_fields == frozenset({"title", "canonical_url"})
