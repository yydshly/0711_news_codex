from typer.testing import CliRunner

from newsradar.cli import app
from newsradar.sources.health_wave import (
    HealthProbeState,
    HealthWaveCandidate,
    HealthWavePlan,
    render_health_wave_report,
    select_health_wave,
)
from newsradar.sources.schema import SourceDefinition

from .test_source_schema import valid_source


def wave_source(source_id: str, *, kind: str, manual: bool = False, auth: str | None = None):
    payload = valid_source()
    payload["id"] = source_id
    payload["name"] = source_id
    payload["access_methods"] = [{
        "kind": kind,
        "url": f"https://www.anthropic.com/{source_id}",
        "priority": 1,
        "requires_manual_approval": manual,
        **({"auth_env": auth} if auth else {}),
    }]
    return SourceDefinition.model_validate(payload)


def test_health_wave_selects_unprobed_and_latest_failed_feeds_only() -> None:
    sources = [
        wave_source("unprobed", kind="rss"),
        wave_source("rss-failed", kind="rss"),
        wave_source("html-blocked", kind="html", manual=True),
        wave_source("reddit", kind="rest_api", auth="REDDIT_CLIENT_ID"),
        wave_source("healthy", kind="rss"),
    ]
    latest = {
        "rss-failed": HealthProbeState("failed", "rss"),
        "html-blocked": HealthProbeState("blocked", "html"),
        "reddit": HealthProbeState("blocked", "rest_api"),
        "healthy": HealthProbeState("success", "rss"),
    }

    plan = select_health_wave(sources, latest, configured_credentials=set())

    assert [item.source.id for item in plan.candidates] == ["rss-failed", "unprobed"]
    assert plan.excluded_reasons["html_policy_blocked"] == 1
    assert plan.excluded_reasons["credential_or_permission_required"] == 1


def test_health_wave_report_and_plan_cli_do_not_probe_or_leak_secrets(
    monkeypatch, tmp_path
) -> None:
    source = wave_source("unprobed", kind="rss")
    plan = HealthWavePlan((HealthWaveCandidate(source, "unprobed"),), {})
    output = tmp_path / "health.md"
    monkeypatch.setattr("newsradar.cli.load_source_tree", lambda root: [source])
    monkeypatch.setattr("newsradar.cli._build_health_wave_plan", lambda sources: plan)
    monkeypatch.setattr(
        "newsradar.cli._probe_sources",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )

    result = CliRunner().invoke(
        app, ["sources", "health-wave", "--root", str(tmp_path), "--output", str(output)]
    )

    assert result.exit_code == 0
    report = output.read_text(encoding="utf-8")
    assert "unprobed" in report
    assert "Authorization" not in report
    assert "Bearer" not in render_health_wave_report(plan)
