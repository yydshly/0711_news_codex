import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from typer.testing import CliRunner

from newsradar.cli import app
from newsradar.settings import Settings
from newsradar.sources.schema import SourceDefinition

from .test_provider_schema import valid_provider
from .test_source_schema import valid_source

runner = CliRunner()


def test_cli_lists_desktop_commands() -> None:
    result = runner.invoke(app, ["desktop", "--help"])

    assert result.exit_code == 0
    assert "autostart-status" in result.stdout


def test_desktop_autostart_command_fixes_project_working_directory(tmp_path) -> None:
    from newsradar import cli

    project_root = tmp_path / "desktop project"
    project_root.mkdir()
    inner_command = subprocess.list2cmdline(
        [sys.executable, "-c", "import os; print(os.getcwd())"]
    )
    command = cli._command_with_project_directory(project_root, inner_command)

    result = subprocess.run(command, shell=False, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert Path(result.stdout.strip()) == project_root


def test_desktop_autostart_command_uses_project_directory_without_secrets() -> None:
    from newsradar import cli

    command = cli._desktop_autostart_command()

    assert "cmd.exe" in command
    assert "cd /d" in command
    assert str(Path(cli.__file__).resolve().parents[2]) in command
    assert "desktop run" in command
    assert "DATABASE_URL" not in command


def test_desktop_autostart_command_reuses_packaged_desktop_executable(
    monkeypatch, tmp_path
) -> None:
    from newsradar import cli

    executable = tmp_path / "NewsCodex.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    command = cli._desktop_autostart_command()

    assert str(executable) in command
    assert "desktop run" not in command


def test_readme_documents_desktop_runtime_controls() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "newsradar desktop run" in readme
    assert "build_windows_desktop.py" in readme
    assert "NewsCodex.exe" in readme
    assert "隐藏到右下角" in readme


def test_waves_commands_validate_and_plan_without_database_or_network(monkeypatch) -> None:
    monkeypatch.setattr(
        "newsradar.cli.create_session",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )
    monkeypatch.setattr(
        "newsradar.cli.httpx.AsyncClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    validate = runner.invoke(
        app, ["waves", "validate", "--profile", "wave_profiles/high-value-ai-tech.yaml"]
    )
    plan = runner.invoke(
        app, ["waves", "plan", "--profile", "wave_profiles/high-value-ai-tech.yaml"]
    )

    assert validate.exit_code == 0
    assert "Validated wave profile high-value-ai-tech" in validate.stdout
    assert plan.exit_code == 0
    assert "total=" in plan.stdout
    assert "fetchable=" in plan.stdout
    assert "blocked_credentials_approval_payment=8" in plan.stdout
    assert "role_coverage=" in plan.stdout


def test_waves_plan_counts_payment_blockers(monkeypatch) -> None:
    from newsradar.waves.planning import WaveMemberSnapshot, WavePlan

    plan = WavePlan(
        profile_id="payment-test",
        members=(
            WaveMemberSnapshot(
                source_id="payment-source",
                provider_id="provider",
                definition_hash="0" * 64,
                roles=("context",),
                availability="requires_payment",
                access_kind="",
                fetchable=False,
                blocked_reason="requires_payment",
            ),
        ),
        digest="1" * 64,
        window_hours=24,
        trend_days=7,
    )
    monkeypatch.setattr("newsradar.cli.load_wave_profile", lambda path: object())
    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [])
    monkeypatch.setattr("newsradar.cli.build_wave_plan", lambda *args: plan)

    result = runner.invoke(app, ["waves", "plan", "--profile", "pyproject.toml"])

    assert result.exit_code == 0
    assert "blocked_credentials_approval_payment=1" in result.stdout


def test_waves_enqueue_status_and_report_do_not_probe_or_call_model(
    monkeypatch, tmp_path: Path
) -> None:
    build_kwargs: dict[str, object] = {}

    class Commands:
        def __init__(self, session):
            pass

        def enqueue_high_value_wave(self, *, plan, trigger):
            assert trigger == "cli"
            return 88

    class Session:
        def commit(self):
            return None

    operation = type(
        "Operation",
        (),
        {
            "id": 88,
            "operation_type": "high_value_news_wave",
            "status": "partial",
            "progress_current": 2,
            "progress_total": 3,
            "requested_scope": {"profile_id": "safe-profile", "profile_digest": "safe"},
            "result_summary": {
                "member_total": 3,
                "completed_members": 2,
                "evidence_capable_members": 2,
                "direct_evidence_fetch_succeeded": 1,
                "confirmed_event_count": 1,
            },
        },
    )()
    members = [
        type(
            "Member",
            (),
            {
                "source_id": "safe-source",
                "provider_id": "safe-provider",
                "fetchable": True,
                "state": "succeeded",
                "result_code": "success",
                "conclusion": (
                    "DATABASE_URL=postgresql://user:database-secret@db/news "
                    "MINIMAX_API_KEY=minimax-secret GITHUB_TOKEN=github-secret "
                    "YOUTUBE_API_KEY=youtube-secret Authorization: Bearer authorization-secret "
                    '{"MINIMAX_API_KEY": "cli-json-secret", '
                    '"nested": [{"github_token": "cli-nested-secret"}]} '
                    "{'YOUTUBE_API_KEY': 'cli-repr-secret'}"
                ),
            },
        )()
    ]

    monkeypatch.setattr(
        "newsradar.cli.load_wave_profile",
        lambda path: type("Profile", (), {"window_hours": 24})(),
    )
    monkeypatch.setattr(
        "newsradar.cli.build_local_wave_plan",
        lambda *args, **kwargs: (
            build_kwargs.update(kwargs)
            or type("Plan", (), {"profile_id": "safe-profile"})()
        ),
    )
    monkeypatch.setattr("newsradar.cli.OperationCommandService", Commands)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(Session()))
    monkeypatch.setattr(
        "newsradar.cli._load_high_value_wave_operation", lambda op: (operation, members)
    )
    monkeypatch.setattr(
        "newsradar.cli.httpx.AsyncClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    enqueue = runner.invoke(app, ["waves", "enqueue", "--profile", "pyproject.toml"])
    status = runner.invoke(app, ["waves", "status", "88"])
    output = tmp_path / "wave.md"
    report = runner.invoke(app, ["waves", "report", "88", "--output", str(output)])

    assert enqueue.exit_code == 0
    assert "88" in enqueue.stdout
    assert build_kwargs == {"profile_path": Path("pyproject.toml"), "window_hours": 24}
    assert status.exit_code == 0
    assert "2/3" in status.stdout
    assert report.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    for secret in (
        "database-secret",
        "minimax-secret",
        "github-secret",
        "youtube-secret",
        "authorization-secret",
        "cli-json-secret",
        "cli-nested-secret",
        "cli-repr-secret",
    ):
        assert secret not in rendered
    assert "Authorization" not in rendered
    assert "Cookie" not in rendered
    assert "证据型成员：2" in rendered
    assert "直接证据抓取成功：1" in rendered


def write_source(root: Path) -> None:
    root.mkdir()
    (root / "source.yaml").write_text(yaml.safe_dump(valid_source()), encoding="utf-8")


def test_validate_command_reports_source_count(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)
    result = runner.invoke(app, ["sources", "validate", "--root", str(root)])
    assert result.exit_code == 0
    assert "Validated 1 source" in result.stdout


def test_catalog_refresh_plan_only_prints_lanes_without_database_or_network(
    monkeypatch, tmp_path: Path
) -> None:
    from newsradar.sources.catalog_refresh import CatalogRefreshPlan

    source_root = tmp_path / "sources"
    provider_root = tmp_path / "providers"
    source_root.mkdir()
    provider_root.mkdir()
    source = SourceDefinition.model_validate(valid_source())
    provider = type("Provider", (), {"id": source.provider_id})()
    plan = CatalogRefreshPlan.from_members(())
    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [source])
    monkeypatch.setattr("newsradar.cli.load_provider_tree", lambda root: [provider])
    monkeypatch.setattr(
        "newsradar.cli.build_catalog_refresh_plan",
        lambda *args, **kwargs: plan,
    )
    monkeypatch.setattr(
        "newsradar.cli.create_session",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )
    monkeypatch.setattr(
        "newsradar.cli.httpx.AsyncClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    result = runner.invoke(
        app,
        [
            "sources",
            "refresh-plan",
            "--root",
            str(source_root),
            "--provider-root",
            str(provider_root),
        ],
    )

    assert result.exit_code == 0
    assert "内容通道" in result.stdout
    assert "能力通道" in result.stdout
    assert "目录通道" in result.stdout


def test_catalog_refresh_enqueue_prints_operation_id_without_direct_probe(
    monkeypatch, tmp_path: Path
) -> None:
    from newsradar.sources.catalog_refresh import CatalogRefreshPlan

    source_root = tmp_path / "sources"
    provider_root = tmp_path / "providers"
    source_root.mkdir()
    provider_root.mkdir()
    source = SourceDefinition.model_validate(valid_source())
    provider = type("Provider", (), {"id": source.provider_id})()
    plan = CatalogRefreshPlan.from_members(())
    synced: list[str] = []

    class SourceRepo:
        def __init__(self, session):
            pass

        def sync(self, values):
            synced.append("sources")

    class ProviderRepo:
        def __init__(self, session):
            pass

        def sync(self, values):
            synced.append("providers")

    class Commands:
        def __init__(self, session):
            pass

        def enqueue_source_catalog_refresh(self, received_plan, *, trigger):
            assert received_plan is plan
            assert trigger == "cli"
            return 77

    class Session:
        def commit(self):
            return None

    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [source])
    monkeypatch.setattr("newsradar.cli.load_provider_tree", lambda root: [provider])
    monkeypatch.setattr("newsradar.cli.build_catalog_refresh_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr("newsradar.cli.SourceRepository", SourceRepo)
    monkeypatch.setattr("newsradar.cli.ProviderRepository", ProviderRepo)
    monkeypatch.setattr("newsradar.cli.OperationCommandService", Commands)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(Session()))
    monkeypatch.setattr(
        "newsradar.cli._probe_sources",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )

    result = runner.invoke(
        app,
        [
            "sources",
            "refresh-enqueue",
            "--root",
            str(source_root),
            "--provider-root",
            str(provider_root),
        ],
    )

    assert result.exit_code == 0
    assert "77" in result.stdout
    assert synced == ["providers", "sources"]


def test_catalog_refresh_status_and_report_are_read_only_and_scrub_secrets(
    monkeypatch, tmp_path: Path
) -> None:
    from newsradar.sources.catalog_refresh import CatalogRefreshLane

    operation = type(
        "Operation",
        (),
        {
            "id": 23,
            "operation_type": "source_catalog_refresh",
            "status": "partial",
            "progress_current": 2,
            "progress_total": 3,
            "requested_scope": {"catalog_digest": "safe-digest"},
        },
    )()
    members = [
        type(
            "Member",
            (),
            {
                "source_id": "safe-source",
                "lane": CatalogRefreshLane.CONTENT.value,
                "state": "failed",
                "result_code": "timeout",
                "content_probe_run_ids": [1, 2, 3],
                "conclusion": "Authorization: definitely-not-for-output",
            },
        )()
    ]

    monkeypatch.setattr(
        "newsradar.cli._load_catalog_refresh_operation", lambda operation_id: (operation, members)
    )
    output = tmp_path / "catalog-refresh.md"

    status = runner.invoke(app, ["sources", "refresh-status", "23"])
    report = runner.invoke(app, ["sources", "refresh-report", "23", "--output", str(output)])

    assert status.exit_code == 0
    assert "2/3" in status.stdout
    assert "内容通道" in status.stdout
    assert "成员状态" in status.stdout
    assert "failed：1" in status.stdout
    assert report.exit_code == 0
    rendered = output.read_text(encoding="utf-8")
    for heading in (
        "批次 ID",
        "目录摘要",
        "完成度",
        "三条通道",
        "结果码",
        "内容三轮证据",
        "能力解锁条件",
        "目录缺口",
        "失败成员",
        "安全边界声明",
    ):
        assert heading in rendered
    assert "definitely-not-for-output" not in rendered
    assert "Authorization" not in rendered


def test_catalog_refresh_summary_contains_only_lane_state_and_result_code_aggregates() -> None:
    from newsradar.sources.catalog_refresh_reporting import summarize_catalog_members

    members = [
        type(
            "Member",
            (),
            {
                "lane": "content",
                "state": "succeeded",
                "result_code": None,
                "content_probe_run_ids": [1, 2, 3],
            },
        )(),
        type(
            "Member",
            (),
            {
                "lane": "capability",
                "state": "blocked",
                "result_code": "requires_approval",
                "content_probe_run_ids": [],
            },
        )(),
    ]

    assert summarize_catalog_members(members) == {
        "lanes": {"capability": 1, "content": 1},
        "states": {"blocked": 1, "succeeded": 1},
        "result_codes": {"requires_approval": 1},
    }


def test_report_command_writes_markdown(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    output = tmp_path / "report.md"
    write_source(root)
    result = runner.invoke(app, ["sources", "report", "--root", str(root), "--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    assert "Anthropic News" in output.read_text(encoding="utf-8")


def test_mixed_report_command_writes_runtime_health_report(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "mixed-sources.md"
    dashboard = object()
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr("newsradar.cli._build_mixed_source_dashboard", lambda session: dashboard)
    monkeypatch.setattr(
        "newsradar.cli.render_mixed_wave_report",
        lambda value: "# 中文混合来源报告\n" if value is dashboard else "unexpected",
    )

    result = runner.invoke(app, ["sources", "mixed-report", "--output", str(output)])

    assert result.exit_code == 0
    assert output.read_text(encoding="utf-8") == "# 中文混合来源报告\n"
    assert "Wrote mixed source health report" in result.stdout


def test_research_audit_commands_are_read_only_and_chinese(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    provider_root = tmp_path / "providers"
    write_source(source_root)
    provider_root.mkdir()

    validate = runner.invoke(
        app,
        [
            "sources",
            "research",
            "validate",
            "--root",
            str(source_root),
            "--provider-root",
            str(provider_root),
        ],
    )
    audit = runner.invoke(
        app,
        [
            "sources",
            "research",
            "audit",
            "--root",
            str(source_root),
            "--provider-root",
            str(provider_root),
        ],
    )

    assert validate.exit_code == 0
    assert "研究审计" in validate.stdout
    assert audit.exit_code == 0
    assert "待研究" in audit.stdout


def test_research_audit_returns_nonzero_for_errors(monkeypatch) -> None:
    from newsradar.research.audit import AuditFinding, ResearchAuditReport

    monkeypatch.setattr(
        "newsradar.cli._research_report",
        lambda *_: ResearchAuditReport(
            provider_count=0,
            target_count=0,
            status_counts={},
            category_counts={},
            method_counts={},
            findings=(AuditFinding("bad", "error", "source", None, "研究缺失"),),
        ),
    )

    result = runner.invoke(app, ["sources", "research", "audit"])

    assert result.exit_code == 1
    assert "研究缺失" in result.stdout


def test_research_probe_rejects_an_unknown_candidate_without_network(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)

    result = runner.invoke(
        app,
        [
            "sources",
            "research",
            "probe",
            "anthropic-news",
            "--candidate",
            "missing-candidate",
            "--root",
            str(root),
        ],
    )

    assert result.exit_code == 2
    assert "未知研究候选" in result.stdout


def test_research_probe_uses_its_owned_safe_client(monkeypatch) -> None:
    from newsradar.research.probes.schema import AcquisitionProbeOutcome, AcquisitionProbeResult

    data = valid_source()
    data["research"] = {
        "candidates": [
            {
                "key": "safe-feed",
                "kind": "rss",
                "implementation": "feedparser",
                "officiality": "official",
                "authentication": "none",
                "roles": ["discovery"],
                "fields": ["title"],
                "limitations": [],
                "evidence": ["https://example.test/feed"],
                "reviewed_at": "2026-07-12",
                "sample_status": "not_run",
                "decision": "supplement",
            }
        ]
    }
    source = SourceDefinition.model_validate(data)
    calls: dict[str, object] = {}

    class Probe:
        async def __aenter__(self):
            calls["entered"] = True
            return self

        async def __aexit__(self, *args):
            calls["closed"] = True

        async def probe(self, source, candidate, limit):
            return AcquisitionProbeResult(
                source_id=source.id,
                candidate_key=candidate.key,
                outcome=AcquisitionProbeOutcome.PARTIAL,
                decision="supplement",
                reason_zh="ok",
            )

    def fake_factory(*args):
        calls["factory_args"] = args
        return Probe()

    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [source])
    monkeypatch.setattr("newsradar.cli.research_probe_for", fake_factory)

    result = runner.invoke(
        app,
        [
            "sources",
            "research",
            "probe",
            "anthropic-news",
            "--candidate",
            "safe-feed",
            "--no-persist",
        ],
    )

    assert result.exit_code == 0
    assert calls["factory_args"] == (source, source.research.candidates[0])
    assert calls["entered"] is True
    assert calls["closed"] is True


def test_youtube_research_probe_uses_safe_factory_and_passes_bounded_video_ids(
    monkeypatch,
) -> None:
    from newsradar.research.probes.schema import (
        AcquisitionProbeOutcome,
        AcquisitionProbeResult,
    )

    data = valid_source()
    data["id"] = "openai-youtube"
    data["provider_id"] = "youtube"
    data["research"] = {
        "candidates": [
            {
                "key": "youtube-data-api",
                "kind": "api_key_api",
                "implementation": "youtube-data-api",
                "officiality": "official",
                "authentication": "api_key",
                "roles": ["metadata"],
                "fields": ["summary"],
                "limitations": [],
                "evidence": ["https://developers.google.com/youtube/v3"],
                "reviewed_at": "2026-07-12",
                "sample_status": "not_run",
                "decision": "supplement",
            }
        ]
    }
    selected = SourceDefinition.model_validate(data)
    received: dict[str, object] = {}

    class ProbeContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def probe(self, source, candidate, limit, video_ids):
            received["factory_args"] = (source, candidate)
            received["video_ids"] = video_ids
            return AcquisitionProbeResult(
                source_id=source.id,
                candidate_key=candidate.key,
                outcome=AcquisitionProbeOutcome.BLOCKED,
                decision="supplement",
                reason_zh="缺少凭据",
            )

    def fake_factory(source, candidate):
        received["factory_args"] = (source, candidate)
        return ProbeContext()

    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [selected])
    monkeypatch.setattr("newsradar.cli.research_probe_for", fake_factory)

    result = runner.invoke(
        app,
        [
            "sources",
            "research",
            "probe",
            "openai-youtube",
            "--candidate",
            "youtube-data-api",
            "--video-id",
            "abcdefghijk",
            "--no-persist",
        ],
    )

    assert result.exit_code == 0
    assert received["factory_args"] == (selected, selected.research.candidates[0])
    assert received["video_ids"] == ("abcdefghijk",)


def test_research_probe_rejects_unbounded_or_malformed_video_ids(monkeypatch) -> None:
    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [])

    result = runner.invoke(
        app,
        [
            "sources",
            "research",
            "probe",
            "openai-youtube",
            "--candidate",
            "youtube-data-api",
            "--video-id",
            "not-valid",
        ],
    )

    assert result.exit_code == 2
    assert "视频 ID" in result.stdout


def test_research_report_writes_markdown_when_only_warnings(monkeypatch, tmp_path: Path) -> None:
    from newsradar.research.audit import AuditFinding, ResearchAuditReport

    monkeypatch.setattr(
        "newsradar.cli._research_report",
        lambda *_: ResearchAuditReport(
            provider_count=0,
            target_count=0,
            status_counts={},
            category_counts={},
            method_counts={},
            findings=(AuditFinding("warn", "warning", "source", None, "需要复核"),),
        ),
    )
    output = tmp_path / "research.md"

    result = runner.invoke(app, ["sources", "research", "report", "--output", str(output)])

    assert result.exit_code == 0
    assert output.exists()
    assert "需要复核" in output.read_text(encoding="utf-8")


def test_probe_command_rejects_unknown_source(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)
    result = runner.invoke(
        app, ["sources", "probe", "missing", "--root", str(root), "--no-persist"]
    )
    assert result.exit_code == 2
    assert "Unknown source id" in result.stdout


def test_probe_command_can_write_live_report(tmp_path: Path, monkeypatch) -> None:
    from .test_risk_and_reporting import success_result

    root = tmp_path / "sources"
    output = tmp_path / "live.md"
    write_source(root)

    async def fake_probe(selected, persist):
        return {selected[0].id: success_result(selected[0].id)}

    monkeypatch.setattr("newsradar.cli._probe_sources", fake_probe)
    result = runner.invoke(
        app,
        [
            "sources",
            "probe",
            "anthropic-news",
            "--root",
            str(root),
            "--no-persist",
            "--report-output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert "success" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("command", "method"),
    [("init", "initialize"), ("start", "start"), ("status", "status"), ("stop", "stop")],
)
def test_db_command_delegates_to_manager(monkeypatch, command: str, method: str) -> None:
    fake = Mock()
    getattr(fake, method).return_value = f"{command} complete"
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", command])

    assert result.exit_code == 0
    assert f"{command} complete" in result.stdout
    getattr(fake, method).assert_called_once_with()


def test_db_command_turns_manager_error_into_safe_cli_failure(monkeypatch) -> None:
    from newsradar.local_postgres import LocalPostgresError

    fake = Mock()
    fake.start.side_effect = LocalPostgresError("Port 55432 is already in use")
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", "start"])

    assert result.exit_code == 1
    assert "Database error: Port 55432 is already in use" in result.output


def test_db_repair_passes_hidden_password_without_printing_it(monkeypatch) -> None:
    fake = Mock()
    fake.repair.return_value = "Database repaired."
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", "repair", "--password", "private-value"])

    assert result.exit_code == 0
    assert "Database repaired." in result.stdout
    assert "private-value" not in result.output
    fake.repair.assert_called_once_with(password="private-value")


def test_db_repair_without_password_does_not_prompt_for_port_migration(monkeypatch) -> None:
    fake = Mock()
    fake.repair.return_value = "Database port migrated."
    monkeypatch.setattr("newsradar.cli.build_local_postgres_manager", lambda: fake)

    result = runner.invoke(app, ["db", "repair"])

    assert result.exit_code == 0
    assert "Database port migrated." in result.stdout
    assert "password" not in result.output.lower()
    fake.repair.assert_called_once_with(password=None)


def test_powershell_wrapper_limits_actions_and_delegates_to_cli() -> None:
    wrapper = Path("scripts/postgres.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("init", "start", "status", "stop", "repair")' in wrapper
    assert "uv run newsradar db $Action" in wrapper
    assert "Get-ChildItem Env:" not in wrapper


def test_diagnostics_create_reports_archive_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.cli.collect_diagnostic_snapshot",
        lambda session: object(),
    )
    archive = tmp_path / "diagnostics.zip"
    monkeypatch.setattr(
        "newsradar.cli.create_diagnostic_bundle", lambda destination, snapshot: archive
    )

    result = runner.invoke(app, ["diagnostics", "create", "--destination", str(tmp_path)])

    assert result.exit_code == 0
    assert str(archive) in result.stdout


def test_provider_validate_command_reports_count(tmp_path: Path) -> None:
    root = tmp_path / "providers"
    root.mkdir()
    (root / "bluesky.yaml").write_text(yaml.safe_dump(valid_provider()), encoding="utf-8")

    result = runner.invoke(app, ["providers", "validate", "--root", str(root)])

    assert result.exit_code == 0
    assert "Validated 1 provider" in result.stdout


def test_coverage_command_filters_provider_and_writes_report(tmp_path: Path) -> None:
    provider_root = tmp_path / "providers"
    source_root = tmp_path / "sources"
    output = tmp_path / "coverage.md"
    provider_root.mkdir()
    source_root.mkdir()
    (provider_root / "bluesky.yaml").write_text(yaml.safe_dump(valid_provider()), encoding="utf-8")
    source = valid_source()
    source.update(
        {
            "provider_id": "bluesky",
            "official_identity_url": "https://bsky.app/profile/anthropic.com",
        }
    )
    (source_root / "source.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "sources",
            "coverage",
            "--provider",
            "bluesky",
            "--provider-root",
            str(provider_root),
            "--root",
            str(source_root),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "Catalog targets | 1" in output.read_text(encoding="utf-8")


def test_fetch_rejects_unapproved_sources_without_one_off(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)

    result = runner.invoke(app, ["fetch", "anthropic-news", "--root", str(root)])

    assert result.exit_code == 2
    assert "No approved ingestion sources" in result.stdout


def test_fetch_one_off_requires_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)

    result = runner.invoke(
        app, ["fetch", "anthropic-news", "--root", str(root), "--one-off"], input="n\n"
    )

    assert result.exit_code == 1
    assert "One-off fetch risk" in result.stdout


def test_fetch_enqueues_without_direct_network_work(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "sources"
    source = valid_source()
    source["ingestion"] = {"enabled": True, "approved_at": "2026-07-12"}
    root.mkdir()
    (root / "source.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    calls: list[dict[str, object]] = []

    class FakeSourceRepository:
        def __init__(self, session):
            pass

        def sync(self, selected):
            assert len(selected) == 1

    class FakeCommands:
        def __init__(self, session):
            pass

        def enqueue_fetch(self, **kwargs):
            calls.append(kwargs)
            return 41

    monkeypatch.setattr("newsradar.cli.SourceRepository", FakeSourceRepository)
    monkeypatch.setattr("newsradar.cli.OperationCommandService", FakeCommands)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))

    result = runner.invoke(app, ["fetch", "anthropic-news", "--root", str(root), "--no-wait"])

    assert result.exit_code == 0
    assert "Queued operations: 41" in result.stdout
    assert calls == [
        {
            "source_id": "anthropic-news",
            "provider": None,
            "dry_run": False,
            "max_items": None,
            "one_off": False,
            "trigger": "cli",
        }
    ]


def test_events_build_wait_prints_terminal_status_while_session_is_open(monkeypatch) -> None:
    calls: list[int] = []

    class Commands:
        def __init__(self, session):
            self.session = session

        def enqueue_event_pipeline(self, **kwargs):
            return 12

        def wait_for_terminal(self, operation_id):
            calls.append(operation_id)
            return type("Terminal", (), {"id": operation_id, "status": "succeeded"})()

    monkeypatch.setattr("newsradar.cli.OperationCommandService", Commands)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))

    result = runner.invoke(app, ["events", "build", "--wait"])

    assert result.exit_code == 0
    assert calls == [12]
    assert "Operation 12: succeeded" in result.stdout


def test_events_quality_report_is_read_only_and_writes_only_requested_output(
    monkeypatch, tmp_path: Path
) -> None:
    output = tmp_path / "nested" / "event-quality.md"
    view = object()
    calls: list[tuple[object, int]] = []

    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.cli.build_event_quality_report_view",
        lambda session, *, window_hours: calls.append((session, window_hours)) or view,
    )
    monkeypatch.setattr(
        "newsradar.cli.render_event_quality_report",
        lambda value: (
            "# Event Intelligence v2 事件质量验收报告\n" if value is view else "unexpected"
        ),
    )

    result = runner.invoke(
        app,
        [
            "events",
            "quality-report",
            "--window-hours",
            "72",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert calls and calls[0][1] == 72
    assert output.read_text(encoding="utf-8").startswith("# Event Intelligence v2")
    assert "已生成事件质量报告" in result.stdout
    assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")) == [
        "nested",
        "nested/event-quality.md",
    ]


def test_events_quality_report_rejects_window_above_safe_limit(monkeypatch) -> None:
    called = False

    def fail_if_called():
        nonlocal called
        called = True

    monkeypatch.setattr("newsradar.cli.create_session", fail_if_called)

    result = runner.invoke(app, ["events", "quality-report", "--window-hours", "721"])

    assert result.exit_code == 2
    assert called is False


def test_events_quality_report_uses_v2_1_default_output(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.cli.build_event_quality_report_view", lambda session, **kwargs: object()
    )
    monkeypatch.setattr("newsradar.cli.render_event_quality_report", lambda view: "# v2.1\n")

    result = runner.invoke(app, ["events", "quality-report"])

    assert result.exit_code == 0
    assert (tmp_path / "reports" / "event-quality-v2-1.md").read_text(
        encoding="utf-8"
    ) == "# v2.1\n"


@pytest.mark.parametrize(
    ("failure_at", "expected_code"),
    [
        ("database", "report_database_unavailable"),
        ("filesystem", "report_write_failed"),
    ],
)
def test_events_quality_report_redacts_database_and_filesystem_errors(
    monkeypatch, tmp_path: Path, failure_at: str, expected_code: str
) -> None:
    secret = "sensitive-database-or-filesystem-detail?token=secret"
    output = tmp_path / "report.md"
    if failure_at == "database":
        monkeypatch.setattr(
            "newsradar.cli.create_session",
            lambda: (_ for _ in ()).throw(RuntimeError(secret)),
        )
    else:
        monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
        monkeypatch.setattr(
            "newsradar.cli.build_event_quality_report_view", lambda session, **kwargs: object()
        )
        monkeypatch.setattr("newsradar.cli.render_event_quality_report", lambda view: "safe")
        monkeypatch.setattr(
            Path,
            "write_text",
            lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError(secret)),
        )

    result = runner.invoke(
        app,
        ["events", "quality-report", "--output", str(output)],
    )

    assert result.exit_code == 1
    output_text = result.stdout + result.stderr
    assert expected_code in output_text
    assert secret not in output_text


def test_worker_command_claims_and_runs_one_queued_operation(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "sources"
    write_source(root)
    handler = object()
    remediation_handler = object()
    wave_handler = object()
    merge_scan_handler = object()
    calls: list[object] = []

    class FakeWorker:
        def __init__(
            self,
            repository,
            worker_id,
            *,
            lease_guard,
            lease_seconds,
            monitor_interval_seconds,
        ):
            assert worker_id == "worker-test"
            assert callable(lease_guard)
            assert lease_seconds == 75
            assert monitor_interval_seconds == 12

        def run_once(self, received_handler):
            calls.append(received_handler)
            return True

    monkeypatch.setattr("newsradar.cli.FetchOperationHandler.production", lambda sources: handler)
    monkeypatch.setattr(
        "newsradar.cli.HighValueWaveHandler.production", lambda sources: wave_handler
    )
    monkeypatch.setattr(
        "newsradar.cli.SourceRemediationHandler.production",
        lambda sources, create_session: remediation_handler,
    )
    monkeypatch.setattr(
        "newsradar.cli.EventMergeOperationHandler.production",
        lambda create_session: merge_scan_handler,
    )
    monkeypatch.setattr("newsradar.cli.Worker", FakeWorker)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "newsradar.cli.get_settings",
        lambda: Settings(worker_lease_seconds=75, worker_heartbeat_seconds=12),
    )

    result = runner.invoke(
        app, ["worker", "--root", str(root), "--worker-id", "worker-test", "--once"]
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].__class__.__name__ == "OperationRouter"
    assert calls[0]._handlers["source_remediation"] is remediation_handler
    assert calls[0]._handlers["high_value_news_wave"] is wave_handler
    assert calls[0]._handlers["event_merge_scan"] is merge_scan_handler
    assert (
        calls[0]._handlers["daily_report_purge"].__class__.__name__
        == "DailyReportPurgeHandler"
    )
    assert "processed 1 operation" in result.stdout


def test_cli_has_no_direct_fetch_batch_runner() -> None:
    from newsradar import cli as cli_module

    assert not hasattr(cli_module, "_fetch_sources")


def test_worker_help_defaults_to_forever() -> None:
    result = runner.invoke(app, ["worker", "--help"])

    assert result.exit_code == 0
    assert "[default: forever]" in result.stdout


def test_serve_runs_runtime_supervisor(monkeypatch) -> None:
    calls: list[str] = []

    class FakeSupervisor:
        def __init__(self, *, host, port, worker_id) -> None:
            assert (host, port, worker_id) == ("127.0.0.1", 8765, None)

        def run(self) -> int:
            calls.append("run")
            return 0

    monkeypatch.setattr("newsradar.cli.RuntimeSupervisor", FakeSupervisor)

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    assert calls == ["run"]


def test_operations_retry_uses_unified_audited_command_service(monkeypatch) -> None:
    calls: list[tuple[int, str]] = []

    class FakeCommands:
        def __init__(self, session):
            pass

        def retry(self, operation_id: int, *, trigger: str) -> int:
            calls.append((operation_id, trigger))
            return 8

    monkeypatch.setattr("newsradar.cli.OperationCommandService", FakeCommands)
    monkeypatch.setattr("newsradar.cli.create_session", lambda: nullcontext(object()))

    result = runner.invoke(app, ["operations", "retry", "7"])

    assert result.exit_code == 0
    assert calls == [(7, "cli")]
    assert "Queued retry for 7 as operation 8" in result.stdout
