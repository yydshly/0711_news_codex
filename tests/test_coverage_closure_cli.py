from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest
from typer.testing import CliRunner

import newsradar.cli as cli
from newsradar.ingestion.coverage_closure import (
    CoverageClosureEntry,
    CoverageClosurePlan,
    CoverageClosureState,
)
from newsradar.ingestion.coverage_closure_runtime import ClosureOperation, CoverageEvidence
from newsradar.sources.schema import SourceDefinition
from tests.test_source_schema import valid_source

runner = CliRunner()


def _source(source_id: str) -> SourceDefinition:
    values = valid_source()
    values.update({"id": source_id, "name": source_id})
    return SourceDefinition.model_validate(values)


def _plan() -> CoverageClosurePlan:
    return CoverageClosurePlan(
        (
            CoverageClosureEntry(
                "covered", "covered", CoverageClosureState.COVERED, None, "已有成功抓取证据。"
            ),
            CoverageClosureEntry(
                "queueable-a", "queueable-a", CoverageClosureState.QUEUEABLE, None, "可试用抓取。"
            ),
            CoverageClosureEntry(
                "queueable-b", "queueable-b", CoverageClosureState.QUEUEABLE, None, "可试用抓取。"
            ),
            CoverageClosureEntry(
                "blocked", "blocked", CoverageClosureState.BLOCKED, "no_probe", "尚无探测。"
            ),
        )
    )


def test_close_coverage_defaults_to_read_only(monkeypatch) -> None:
    calls: list[str] = []

    class Service:
        def __init__(self, session) -> None:
            pass

        def plan(self, sources):
            calls.append("plan")
            return _plan()

    monkeypatch.setattr(cli, "load_source_tree", lambda root: [_source("one")])
    monkeypatch.setattr(cli, "create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(cli, "CoverageClosureService", Service)

    result = runner.invoke(cli.app, ["sources", "close-coverage"])

    assert result.exit_code == 0
    assert "仅预览，未写入数据库、未创建抓取任务" in result.stdout
    assert "范围内：4；已覆盖：1；可入队：2；阻塞：1" in result.stdout
    assert calls == ["plan"]


def test_close_coverage_rejects_wait_without_execute() -> None:
    result = runner.invoke(cli.app, ["sources", "close-coverage", "--wait"])

    assert result.exit_code == 2
    assert "--wait 必须与 --execute 一起使用" in result.stdout


@pytest.mark.parametrize("max_items", ["0", "6"])
def test_close_coverage_rejects_out_of_range_max_items(max_items: str) -> None:
    result = runner.invoke(
        cli.app,
        ["sources", "close-coverage", "--max-items", max_items],
    )

    assert result.exit_code == 2


def test_close_coverage_execute_wait_writes_report_after_all_terminals(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    output = tmp_path / "coverage.md"

    class Session:
        def commit(self) -> None:
            calls.append("commit")

    class Repository:
        def __init__(self, session) -> None:
            pass

        def sync(self, sources) -> None:
            calls.append("sync")

    class Service:
        def __init__(self, session) -> None:
            self.plan_count = 0

        def plan(self, sources):
            self.plan_count += 1
            calls.append("plan")
            return _plan()

        def evidence(self, source_ids):
            calls.append("evidence")
            return (CoverageEvidence("queueable-a", "succeeded", None, 1),)

        def enqueue(self, plan, *, max_items, trigger):
            calls.append("enqueue")
            assert max_items == 5
            assert trigger == "coverage-closure"
            return (ClosureOperation("queueable-a", 11), ClosureOperation("queueable-b", 12))

        def wait(self, operations):
            calls.append("wait")
            return (
                ClosureOperation("queueable-a", 11, "succeeded"),
                ClosureOperation("queueable-b", 12, "failed"),
            )

    monkeypatch.setattr(cli, "load_source_tree", lambda root: [_source("one")])
    monkeypatch.setattr(cli, "create_session", lambda: nullcontext(Session()))
    monkeypatch.setattr(cli, "SourceRepository", Repository)
    monkeypatch.setattr(cli, "CoverageClosureService", Service)
    monkeypatch.setattr(
        cli,
        "render_coverage_closure_report",
        lambda **kwargs: calls.append("render") or "# 来源覆盖收口 v1 验收报告\n",
    )

    result = runner.invoke(
        cli.app,
        [
            "sources",
            "close-coverage",
            "--execute",
            "--wait",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "操作 11：succeeded" in result.stdout
    assert "操作 12：failed" in result.stdout
    assert output.read_text(encoding="utf-8").startswith("# 来源覆盖收口 v1 验收报告")
    assert calls == [
        "sync",
        "commit",
        "plan",
        "evidence",
        "enqueue",
        "wait",
        "plan",
        "evidence",
        "render",
    ]
