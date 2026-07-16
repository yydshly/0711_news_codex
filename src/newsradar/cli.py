from __future__ import annotations

import asyncio
import os
import re
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from newsradar.ai.health import check_minimax_config, check_minimax_live
from newsradar.ai.minimax import ModelUsage
from newsradar.credentials import SettingsCredentials
from newsradar.db.models import (
    EventScoreRecord,
    EventVersionRecord,
    HighValueWaveMemberRecord,
    OperationRunRecord,
    SourceAcquisitionCandidateRecord,
    SourceAcquisitionProbeRunRecord,
    SourceCatalogRefreshMemberRecord,
    SourceProbeRunRecord,
)
from newsradar.db.session import create_session
from newsradar.diagnostics import collect_diagnostic_snapshot, create_diagnostic_bundle
from newsradar.events.reporting import (
    build_event_quality_report_view,
    render_event_quality_report,
)
from newsradar.events.runtime import EventOperationHandler
from newsradar.ingestion.coverage_closure_reporting import (
    COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS,
    CatalogAdjustment,
    render_coverage_closure_report,
)
from newsradar.ingestion.coverage_closure_runtime import (
    COVERAGE_CLOSURE_TRIGGER,
    CoverageClosureService,
)
from newsradar.ingestion.trial import evaluate_trial_eligibility
from newsradar.local_postgres import (
    LocalPostgresError,
    build_local_postgres_manager,
)
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.fetch_runtime import FetchOperationHandler
from newsradar.operations.logging import redact
from newsradar.operations.repository import OperationRepository
from newsradar.operations.router import OperationRouter
from newsradar.operations.worker import Worker
from newsradar.providers.probes import probe_providers
from newsradar.providers.reporting import render_coverage_report
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.remediation.reporting import render_remediation_report
from newsradar.remediation.repository import RemediationRepository
from newsradar.remediation.runtime import SourceRemediationHandler
from newsradar.research.audit import audit_source_catalog
from newsradar.research.probes.factory import research_probe_for
from newsradar.research.reporting import render_research_report
from newsradar.runtime import RuntimeSupervisor
from newsradar.settings import get_settings
from newsradar.sources.catalog_reconcile import (
    CatalogReconcileBlocked,
    apply_reconcile_plan,
    build_reconcile_plan,
)
from newsradar.sources.catalog_refresh import build_catalog_refresh_plan
from newsradar.sources.catalog_refresh_reporting import (
    render_catalog_refresh_report,
    summarize_catalog_members,
)
from newsradar.sources.catalog_refresh_runtime import CatalogRefreshHandler
from newsradar.sources.health_wave import (
    HealthProbeState,
    render_health_wave_report,
    select_health_wave,
)
from newsradar.sources.mixed_wave_reporting import render_mixed_wave_report
from newsradar.sources.probes.factory import ProbeFactory
from newsradar.sources.probes.runner import ProbeRunner
from newsradar.sources.reporting import render_source_report
from newsradar.sources.repository import SourceRepository
from newsradar.sources.yaml_loader import load_source_tree
from newsradar.waves.loader import load_wave_profile
from newsradar.waves.planning import build_wave_plan
from newsradar.waves.reporting import render_high_value_wave_report
from newsradar.waves.runtime import HighValueWaveHandler
from newsradar.waves.scheduling import enqueue_due

app = typer.Typer(help="News Codex source intelligence registry")
sources_app = typer.Typer(help="Validate, sync, probe, and report audited sources")
research_app = typer.Typer(help="只读来源研究审计")
providers_app = typer.Typer(help="Validate, sync, probe, and report source providers")
remediate_app = typer.Typer(help="Read and run bounded source remediation")
db_app = typer.Typer(help="Manage the project-local PostgreSQL runtime")
app.add_typer(sources_app, name="sources")
sources_app.add_typer(research_app, name="research")
sources_app.add_typer(remediate_app, name="remediate")
app.add_typer(providers_app, name="providers")
app.add_typer(db_app, name="db")
operations_app = typer.Typer(help="Inspect and retry durable operations")
app.add_typer(operations_app, name="operations")
events_app = typer.Typer(help="Build and inspect durable event intelligence")
app.add_typer(events_app, name="events")
diagnostics_app = typer.Typer(help="Create scrubbed local runtime diagnostics")
app.add_typer(diagnostics_app, name="diagnostics")
minimax_app = typer.Typer(help="Inspect the local MiniMax runtime without exposing secrets")
app.add_typer(minimax_app, name="minimax")
waves_app = typer.Typer(help="Validate and plan frozen high-value source waves")
app.add_typer(waves_app, name="waves")

RootOption = Annotated[
    Path, typer.Option("--root", exists=True, file_okay=False, resolve_path=True)
]
ProviderRootOption = Annotated[
    Path, typer.Option("--root", exists=True, file_okay=False, resolve_path=True)
]
CatalogProviderRootOption = Annotated[
    Path, typer.Option("--provider-root", exists=True, file_okay=False, resolve_path=True)
]
WorkerProviderRootOption = Annotated[
    Path, typer.Option("--provider-root", exists=True, file_okay=False, resolve_path=True)
]


@waves_app.command("validate")
def validate_wave_profile(
    profile: Annotated[Path, typer.Option("--profile", exists=True, dir_okay=False)],
) -> None:
    loaded = load_wave_profile(profile)
    typer.echo(f"Validated wave profile {loaded.id}: {len(loaded.source_ids)} sources")


@waves_app.command("plan")
def plan_wave(
    profile: Annotated[Path, typer.Option("--profile", exists=True, dir_okay=False)],
) -> None:
    loaded = load_wave_profile(profile)
    plan = build_wave_plan(loaded, load_source_tree(Path("sources")), {}, set())
    protected_reasons = {
        "missing_credentials",
        "requires_approval",
        "requires_payment",
        "availability_requires_approval",
        "availability_requires_payment",
    }
    protected = sum(member.blocked_reason in protected_reasons for member in plan.blocked)
    covered_roles = sorted({role for member in plan.members for role in member.roles})
    typer.echo(
        f"total={len(plan.members)} fetchable={len(plan.fetchable)} "
        f"blocked_credentials_approval_payment={protected} "
        f"role_coverage={','.join(covered_roles)} digest={plan.digest}"
    )


def _wave_plan_from_local_catalog(profile: Path, session):
    """Build a frozen wave plan from reviewed local files and persisted probe state only."""
    loaded = load_wave_profile(profile)
    sources = load_source_tree(Path("sources"))
    providers = load_provider_tree(Path("providers"))
    ProviderRepository(session).sync(providers)
    SourceRepository(session).sync(sources)
    session.commit()
    repository = SourceRepository(session)
    source_ids = list(loaded.source_ids)
    probes = repository.latest_probe_snapshots(source_ids)
    return build_wave_plan(
        loaded,
        sources,
        probes,
        SettingsCredentials().configured_names(),
        successful_fetch_access=repository.successful_fetch_access(source_ids),
    )


@waves_app.command("enqueue")
def enqueue_wave(
    profile: Annotated[Path, typer.Option("--profile", exists=True, dir_okay=False)],
) -> None:
    """Synchronize reviewed YAML and queue one frozen wave; this command never probes."""
    try:
        with create_session() as session:
            plan = _wave_plan_from_local_catalog(profile, session)
            operation_id = OperationCommandService(session).enqueue_high_value_wave(
                plan=plan, trigger="cli"
            )
    except ValueError as exc:
        typer.echo(f"无法创建高价值新闻波次：{exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(f"已创建高价值新闻波次任务：{operation_id}")


@waves_app.command("enqueue-due")
def enqueue_due_wave(
    profile: Annotated[Path, typer.Option("--profile", exists=True, dir_okay=False)],
) -> None:
    """Queue one due frozen wave only; this command never starts a worker or fetch."""
    try:
        with create_session() as session:
            plan = _wave_plan_from_local_catalog(profile, session)
            result = enqueue_due(OperationCommandService(session), plan, now=datetime.now(UTC))
    except ValueError as exc:
        typer.echo(f"enqueue_due_failed: {exc}", err=True)
        raise typer.Exit(2) from None
    if result.operation_id is None:
        typer.echo(f"enqueue_due_not_queued: {result.reason}")
    else:
        typer.echo(f"enqueue_due_queued: {result.operation_id}")


def _load_high_value_wave_operation(operation_id: int):
    with create_session() as session:
        operation = session.get(OperationRunRecord, operation_id)
        if operation is None or operation.operation_type != "high_value_news_wave":
            raise LookupError("high_value_news_wave_not_found")
        members = list(
            session.scalars(
                select(HighValueWaveMemberRecord)
                .where(HighValueWaveMemberRecord.operation_run_id == operation_id)
                .order_by(HighValueWaveMemberRecord.source_id)
            )
        )
    return operation, members


def _load_high_value_wave_report(operation_id: int):
    """Read immutable event refs from one wave without falling back to current events."""
    operation, members = _load_high_value_wave_operation(operation_id)
    summary = operation.result_summary if isinstance(operation.result_summary, dict) else {}
    snapshots = summary.get("event_version_snapshots", [])
    if not isinstance(snapshots, list) or not snapshots:
        return operation, members, []
    with create_session() as session:
        events: list[dict[str, object]] = []
        for ref in snapshots:
            if not isinstance(ref, dict):
                continue
            event_id, version_number = ref.get("event_id"), ref.get("version_number")
            if not isinstance(event_id, int) or not isinstance(version_number, int):
                continue
            version = session.scalar(
                select(EventVersionRecord).where(
                    EventVersionRecord.event_id == event_id,
                    EventVersionRecord.version_number == version_number,
                )
            )
            score = session.scalar(
                select(EventScoreRecord).where(
                    EventScoreRecord.event_id == event_id,
                    EventScoreRecord.version_number == version_number,
                )
            )
            if version is None or score is None:
                continue
            payload = version.payload if isinstance(version.payload, dict) else {}
            enrichment = (
                payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {}
            )
            trend = payload.get("trend") if isinstance(payload.get("trend"), dict) else {}
            events.append(
                {
                    "title": version.zh_title or enrichment.get("zh_title") or "未命名事件",
                    "signal_state": "confirmed"
                    if payload.get("status") == "confirmed"
                    else "early_signal",
                    "heat": score.heat,
                    "trend": trend.get("direction", "暂无"),
                    "evidence_roots": score.breakdown.get("independent_root_count", 0)
                    if isinstance(score.breakdown, dict)
                    else 0,
                }
            )
    return operation, members, events


def _wave_member_counts(members) -> dict[str, int]:
    counts: dict[str, int] = {}
    for member in members:
        counts[member.state] = counts.get(member.state, 0) + 1
    return counts


@waves_app.command("status")
def show_wave_status(operation_id: Annotated[int, typer.Argument(min=1)]) -> None:
    """Show frozen wave state only; no fetch, model call, or retry is performed."""
    try:
        operation, members = _load_high_value_wave_operation(operation_id)
    except LookupError:
        typer.echo("未找到高价值新闻波次任务", err=True)
        raise typer.Exit(2) from None
    total = operation.progress_total if operation.progress_total is not None else len(members)
    typer.echo(f"高价值新闻波次 {operation.id}：{operation.status}")
    typer.echo(f"完成度：{operation.progress_current}/{total}")
    counts = _wave_member_counts(members)
    if counts:
        typer.echo(
            "成员状态：" + "，".join(f"{key}={value}" for key, value in sorted(counts.items()))
        )


@waves_app.command("report")
def write_wave_report(
    operation_id: Annotated[int, typer.Argument(min=1)],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Render a scrubbed Chinese report for one frozen wave without touching the network."""
    try:
        operation, members, events = _load_high_value_wave_report(operation_id)
    except LookupError:
        typer.echo("未找到高价值新闻波次任务", err=True)
        raise typer.Exit(2) from None
    total = operation.progress_total if operation.progress_total is not None else len(members)
    scope = operation.requested_scope if isinstance(operation.requested_scope, dict) else {}
    summary = operation.result_summary if isinstance(operation.result_summary, dict) else {}
    lines = [
        "# 高价值 AI/技术新闻波次报告",
        "",
        f"- 任务：{operation.id}",
        f"- 状态：{operation.status}",
        f"- 完成度：{operation.progress_current}/{total}",
        f"- Profile：{redact(scope.get('profile_id', 'unknown'))}",
        f"- 已完成成员：{redact(summary.get('completed_members', 0))}",
        "",
        "## 成员结果",
        "",
        "| 来源 | 平台 | 可抓取 | 状态 | 结果码 | 结论 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for member in members:
        lines.append(
            "| {source} | {provider} | {fetchable} | {state} | {code} | {conclusion} |".format(
                source=redact(member.source_id),
                provider=redact(member.provider_id),
                fetchable="是" if member.fetchable else "否",
                state=redact(member.state),
                code=redact(member.result_code or "-"),
                conclusion=redact(member.conclusion or "-").replace("|", "\\|"),
            )
        )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            render_high_value_wave_report(operation, members, events), encoding="utf-8"
        )
    except OSError:
        typer.echo("high_value_wave_report_write_failed", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"已生成高价值新闻波次报告：{output}")


def _parse_utc_baseline(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise typer.BadParameter("必须使用带时区的 ISO 8601 时间") from None
    if parsed.tzinfo is None:
        raise typer.BadParameter("必须包含时区，例如 2026-07-13T00:00:00+00:00")
    return parsed.astimezone(UTC)


def _run_db_action(action: str) -> None:
    try:
        message = getattr(build_local_postgres_manager(), action)()
    except LocalPostgresError as exc:
        typer.echo(f"Database error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(message)


@db_app.command("init")
def initialize_database() -> None:
    _run_db_action("initialize")


@db_app.command("start")
def start_database() -> None:
    _run_db_action("start")


@db_app.command("status")
def database_status() -> None:
    _run_db_action("status")


@db_app.command("stop")
def stop_database() -> None:
    _run_db_action("stop")


@db_app.command("repair")
def repair_database(
    password: Annotated[
        str | None,
        typer.Option("--password", hide_input=True),
    ] = None,
) -> None:
    try:
        message = build_local_postgres_manager().repair(password=password)
    except LocalPostgresError as exc:
        typer.echo(f"Database error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(message)


@app.command("web")
def run_web(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
) -> None:
    import uvicorn

    from newsradar.web import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@minimax_app.command("check")
def check_minimax(
    live: Annotated[bool, typer.Option("--live", help="Run one bounded provider check")] = False,
) -> None:
    """Show safe MiniMax configuration, optionally verifying one structured call."""
    settings = get_settings()
    if not live:
        result = check_minimax_config(settings)
        typer.echo(
            "MiniMax configuration: "
            f"configured={result.configured} region={result.region} "
            f"fast_model={result.fast_model} deep_model={result.deep_model}"
        )
        return

    usages: list[ModelUsage] = []

    async def run_check():
        async with httpx.AsyncClient(trust_env=settings.http_trust_env) as http:
            return await check_minimax_live(settings, http, usages.append)

    result = asyncio.run(run_check())
    if usages:
        with create_session() as session:
            repository = SourceRepository(session)
            for usage in usages:
                repository.save_model_usage(usage)
            session.commit()
    typer.echo(
        "MiniMax live check: "
        f"configured={result.config.configured} region={result.config.region} "
        f"model_visible={result.model_visible} model_http={result.model_http_status} "
        f"structured_outcome={result.structured_outcome} "
        f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} "
        f"latency_ms={result.latency_ms:.0f} error={result.error_code or 'none'}"
    )
    if not result.model_visible or result.structured_outcome != "success":
        raise typer.Exit(1)


@app.command("fetch")
def fetch_sources(
    source_id: Annotated[str | None, typer.Argument()] = None,
    root: RootOption = Path("sources"),
    approved: Annotated[bool, typer.Option("--approved/--no-approved")] = True,
    one_off: Annotated[bool, typer.Option("--one-off")] = False,
    trial: Annotated[bool, typer.Option("--trial")] = False,
    provider: Annotated[str | None, typer.Option()] = None,
    max_items: Annotated[int | None, typer.Option(min=1)] = None,
    dry_run: Annotated[bool, typer.Option()] = False,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
    remediation_content_probe_id: Annotated[
        int | None, typer.Option("--remediation-content-probe-id", min=1)
    ] = None,
) -> None:
    """Queue audited source fetches; only a Worker performs network work."""
    if trial and one_off:
        typer.echo("--trial cannot be used with --one-off")
        raise typer.Exit(2)
    if trial and not approved:
        typer.echo("--trial cannot be used with --no-approved")
        raise typer.Exit(2)
    if remediation_content_probe_id is not None and (not trial or source_id is None):
        typer.echo("Remediation content linkage requires --trial and one explicit source")
        raise typer.Exit(2)
    sources = load_source_tree(root)
    selected = [source for source in sources if source_id is None or source.id == source_id]
    if provider:
        selected = [source for source in selected if source.provider_id == provider]
    if not selected:
        typer.echo("No matching sources")
        raise typer.Exit(2)
    if one_off and source_id is None:
        typer.echo("--one-off requires an explicit source id")
        raise typer.Exit(2)
    if trial:
        with create_session() as session:
            if remediation_content_probe_id is not None:
                content_probe = session.get(SourceProbeRunRecord, remediation_content_probe_id)
                if (
                    content_probe is None
                    or content_probe.source_id != source_id
                    or content_probe.remediation_acquisition_probe_id is None
                ):
                    typer.echo("Remediation content probe is not linked to this source")
                    raise typer.Exit(2)
            repository = SourceRepository(session)
            repository.sync(selected)
            snapshots = repository.latest_probe_snapshots([source.id for source in selected])
            candidates = []
            excluded: list[tuple[str, str]] = []
            for source in selected:
                decision = evaluate_trial_eligibility(source, snapshots.get(source.id))
                if decision.eligible:
                    candidates.append(source)
                else:
                    excluded.append((source.id, decision.code or "ineligible"))
            typer.echo(f"Trial candidates: {len(candidates)}")
            for source_name, code in excluded:
                typer.echo(f"Trial excluded: {source_name} ({code})")
            if not candidates:
                raise typer.Exit(2)
            commands = OperationCommandService(session)
            operation_ids = [
                commands.enqueue_fetch(
                    source_id=source.id,
                    provider=provider,
                    dry_run=dry_run,
                    max_items=max_items,
                    trial=True,
                    **(
                        {"remediation_content_probe_id": remediation_content_probe_id}
                        if remediation_content_probe_id is not None
                        else {}
                    ),
                    trigger="cli",
                )
                for source in candidates
            ]
            typer.echo(f"Queued operations: {', '.join(map(str, operation_ids))}")
            if not wait:
                return
            terminals = [commands.wait_for_terminal(operation_id) for operation_id in operation_ids]
            terminal_states = [(operation.id, operation.status) for operation in terminals]
        for operation_id, status in terminal_states:
            typer.echo(f"Operation {operation_id}: {status}")
        if any(status not in {"succeeded", "partial"} for _, status in terminal_states):
            raise typer.Exit(1)
        return
    if one_off:
        source = selected[0]
        typer.echo(
            f"One-off fetch risk: source={source.id} risk={source.total_risk}/25 "
            f"impact=network request and RawItem persistence"
        )
        if not typer.confirm("Proceed with this one-off fetch?"):
            raise typer.Exit(1)
    else:
        if not approved:
            typer.echo("--no-approved requires an explicit source id with --one-off")
            raise typer.Exit(2)
        selected = [source for source in selected if source.ingestion.enabled]
        if not selected:
            typer.echo("No approved ingestion sources; use SOURCE_ID --one-off to request one.")
            raise typer.Exit(2)
    with create_session() as session:
        SourceRepository(session).sync(selected)
        commands = OperationCommandService(session)
        operation_ids = [
            commands.enqueue_fetch(
                source_id=source.id,
                provider=provider,
                dry_run=dry_run,
                max_items=max_items,
                one_off=one_off,
                trigger="cli",
            )
            for source in selected
        ]
        typer.echo(f"Queued operations: {', '.join(map(str, operation_ids))}")
        if not wait:
            return
        terminals = [commands.wait_for_terminal(operation_id) for operation_id in operation_ids]
        terminal_states = [(operation.id, operation.status) for operation in terminals]
    for operation_id, status in terminal_states:
        typer.echo(f"Operation {operation_id}: {status}")
    if any(status not in {"succeeded", "partial"} for _, status in terminal_states):
        raise typer.Exit(1)


@operations_app.command("list")
def list_operations() -> None:
    from sqlalchemy import select

    with create_session() as session:
        for operation in session.scalars(
            select(OperationRunRecord).order_by(OperationRunRecord.id.desc())
        ):
            typer.echo(f"{operation.id} {operation.operation_type} {operation.status}")


@operations_app.command("show")
def show_operation(operation_id: int) -> None:
    with create_session() as session:
        operation = session.get(OperationRunRecord, operation_id)
        if operation is None:
            raise typer.Exit(2)
        typer.echo(f"{operation.id} {operation.operation_type} {operation.status}")
        typer.echo(str(operation.requested_scope))


@operations_app.command("retry")
def retry_operation(operation_id: int) -> None:
    with create_session() as session:
        try:
            retry_id = OperationCommandService(session).retry(operation_id, trigger="cli")
        except ValueError:
            raise typer.Exit(2) from None
    typer.echo(f"Queued retry for {operation_id} as operation {retry_id}")


@app.command("worker")
def run_worker(
    root: RootOption = Path("sources"),
    provider_root: WorkerProviderRootOption = Path("providers"),
    worker_id: Annotated[str | None, typer.Option()] = None,
    once: Annotated[bool, typer.Option("--once/--forever")] = False,
    poll_seconds: Annotated[float, typer.Option(min=0.1, max=60.0)] = 1.0,
) -> None:
    """Consume durable operations; network work only occurs in this process."""
    sources = load_source_tree(root)
    providers = load_provider_tree(provider_root)
    handler = OperationRouter(
        {
            "fetch": FetchOperationHandler.production(sources),
            "source_remediation": SourceRemediationHandler.production(sources, create_session),
            "source_catalog_refresh": CatalogRefreshHandler.production(
                sources, providers, create_session
            ),
            "high_value_news_wave": HighValueWaveHandler.production(sources),
            "event_pipeline": EventOperationHandler.production(create_session),
            "event_recluster": EventOperationHandler.production(create_session),
            "event_enrich": EventOperationHandler.production(create_session),
            "event_merge": EventOperationHandler.production(create_session),
            "event_split": EventOperationHandler.production(create_session),
            "event_exclude": EventOperationHandler.production(create_session),
        }
    )
    settings = get_settings()
    identifier = worker_id or f"{socket.gethostname()}-{os.getpid()}"
    processed_count = 0
    while True:
        with create_session() as session:

            def guard(lease):
                # This separate session is deliberate: the production handler owns its
                # own DB session while doing network I/O, so the lease can be renewed
                # without sharing a SQLAlchemy Session across threads.
                with create_session() as monitor_session:
                    monitor = OperationRepository(monitor_session)
                    renewed = monitor.renew_lease(
                        lease, lease_seconds=settings.worker_lease_seconds
                    )
                    return renewed and not monitor.is_cancel_requested(lease)

            processed = Worker(
                OperationRepository(session),
                identifier,
                lease_guard=guard,
                lease_seconds=settings.worker_lease_seconds,
                monitor_interval_seconds=settings.worker_heartbeat_seconds,
            ).run_once(handler)
        if processed:
            processed_count += 1
        if once:
            break
        if not processed:
            time.sleep(poll_seconds)
    typer.echo(f"Worker {identifier} processed {processed_count} operation(s)")


@events_app.command("build")
def build_events(
    hours: Annotated[int, typer.Option("--hours", min=1)] = 24,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
) -> None:
    with create_session() as session:
        commands = OperationCommandService(session)
        operation_id = commands.enqueue_event_pipeline(window_hours=hours, trigger="cli")
        typer.echo(f"Queued event pipeline as operation {operation_id}")
        if not wait:
            return
        terminal = commands.wait_for_terminal(operation_id)
        terminal_state = (terminal.id, terminal.status)
    typer.echo(f"Operation {terminal_state[0]}: {terminal_state[1]}")
    if terminal_state[1] not in {"succeeded", "partial"}:
        raise typer.Exit(1)


@events_app.command("list")
def list_events() -> None:
    from sqlalchemy import select

    from newsradar.db.models import EventRecord

    with create_session() as session:
        for event in session.scalars(select(EventRecord).order_by(EventRecord.updated_at.desc())):
            typer.echo(f"{event.id} {event.status} {event.canonical_key}")


@events_app.command("show")
def show_event(event_id: int) -> None:
    from newsradar.db.models import EventRecord

    with create_session() as session:
        event = session.get(EventRecord, event_id)
        if event is None:
            raise typer.Exit(2)
        typer.echo(f"{event.id} {event.status} {event.canonical_key}")


@events_app.command("quality-report")
def event_quality_report(
    window_hours: Annotated[int, typer.Option("--window-hours", min=1, max=720)] = 72,
    output: Annotated[Path, typer.Option("--output")] = Path("reports/event-quality-v2-1.md"),
) -> None:
    """Write a read-only, secret-free Event Intelligence v2.1 acceptance report."""
    try:
        with create_session() as session:
            view = build_event_quality_report_view(session, window_hours=window_hours)
    except (RuntimeError, SQLAlchemyError):
        typer.echo("事件质量报告读取失败（report_database_unavailable）", err=True)
        raise typer.Exit(1) from None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_event_quality_report(view), encoding="utf-8")
    except OSError:
        typer.echo("事件质量报告写入失败（report_write_failed）", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"已生成事件质量报告：{output}")


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
    worker_id: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Start the local Web UI and durable Worker together."""
    exit_code = RuntimeSupervisor(host=host, port=port, worker_id=worker_id).run()
    if exit_code:
        raise typer.Exit(exit_code)


@diagnostics_app.command("create")
def create_diagnostics(
    destination: Annotated[Path, typer.Option()] = Path(".local/diagnostics"),
) -> None:
    """Create a bounded ZIP with scrubbed operational evidence."""
    with create_session() as session:
        snapshot = collect_diagnostic_snapshot(session)
    archive = create_diagnostic_bundle(destination, snapshot)
    typer.echo(f"Created scrubbed diagnostic bundle: {archive}")


@providers_app.command("validate")
def validate_providers(root: ProviderRootOption = Path("providers")) -> None:
    providers = load_provider_tree(root)
    typer.echo(
        f"Validated {len(providers)} provider{'s' if len(providers) != 1 else ''} from {root}"
    )


@providers_app.command("sync")
def sync_providers(root: ProviderRootOption = Path("providers")) -> None:
    providers = load_provider_tree(root)
    with create_session() as session:
        result = ProviderRepository(session).sync(providers)
        session.commit()
    typer.echo(
        f"Synced {len(providers)} providers: {result.created} created, "
        f"{result.updated} updated, {result.unchanged} unchanged"
    )


async def _probe_providers(selected, persist: bool):
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await probe_providers(selected, client)
    if persist:
        with create_session() as session:
            repository = ProviderRepository(session)
            repository.sync(selected)
            for result in results.values():
                repository.save_probe(**result.model_dump())
            session.commit()
    return results


@providers_app.command("probe")
def probe_provider_capabilities(
    root: ProviderRootOption = Path("providers"),
    all_providers: Annotated[bool, typer.Option("--all")] = False,
    persist: Annotated[bool, typer.Option("--persist/--no-persist")] = True,
) -> None:
    if not all_providers:
        typer.echo("Provide --all")
        raise typer.Exit(2)
    providers = load_provider_tree(root)
    results = asyncio.run(_probe_providers(providers, persist))
    for provider in providers:
        result = results[provider.id]
        typer.echo(
            f"{provider.id}: {result.outcome} availability={result.availability} "
            f"reason={result.reason}"
        )


@providers_app.command("report")
def report_providers(
    root: ProviderRootOption = Path("providers"),
    source_root: Annotated[
        Path, typer.Option("--source-root", exists=True, file_okay=False, resolve_path=True)
    ] = Path("sources"),
    output: Annotated[Path, typer.Option("--output")] = Path("reports/source-coverage.md"),
    history: Annotated[bool, typer.Option("--history/--no-history")] = False,
) -> None:
    providers = load_provider_tree(root)
    sources = load_source_tree(source_root)
    results = None
    if history:
        with create_session() as session:
            results = ProviderRepository(session).latest_probes()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_coverage_report(providers, sources, results), encoding="utf-8")
    typer.echo(f"Wrote provider coverage report to {output}")


@sources_app.command("validate")
def validate_sources(root: RootOption = Path("sources")) -> None:
    sources = load_source_tree(root)
    typer.echo(f"Validated {len(sources)} source{'s' if len(sources) != 1 else ''} from {root}")


@sources_app.command("sync")
def sync_sources(root: RootOption = Path("sources")) -> None:
    sources = load_source_tree(root)
    with create_session() as session:
        result = SourceRepository(session).sync(sources)
        session.commit()
    typer.echo(
        f"Synced {len(sources)} sources: {result.created} created, "
        f"{result.updated} updated, {result.unchanged} unchanged"
    )


def _catalog_refresh_plan(root: Path, provider_root: Path):
    """Load only reviewed YAML and create a pure, deterministic lane plan."""
    sources = load_source_tree(root)
    providers = load_provider_tree(provider_root)
    return (
        sources,
        providers,
        build_catalog_refresh_plan(
            sources,
            providers,
            latest={},
            configured_credentials=SettingsCredentials().configured_names(),
        ),
    )


@sources_app.command("refresh-plan")
def show_catalog_refresh_plan(
    root: RootOption = Path("sources"),
    provider_root: CatalogProviderRootOption = Path("providers"),
) -> None:
    """Show the three catalog lanes; this command never opens the database or network."""
    _, _, plan = _catalog_refresh_plan(root, provider_root)
    lane_labels = {
        "content": "内容通道",
        "capability": "能力通道",
        "catalog": "目录通道",
    }
    typer.echo("来源目录刷新计划（仅计划，不创建任务）")
    for lane in ("content", "capability", "catalog"):
        count = sum(member.lane.value == lane for member in plan.members)
        typer.echo(f"{lane_labels[lane]}：{count}")
    typer.echo(f"目录摘要：{plan.catalog_digest}")


@sources_app.command("refresh-enqueue")
def enqueue_catalog_refresh(
    root: RootOption = Path("sources"),
    provider_root: CatalogProviderRootOption = Path("providers"),
) -> None:
    """Synchronize reviewed YAML and enqueue one frozen batch; Worker does all probing."""
    sources, providers, plan = _catalog_refresh_plan(root, provider_root)
    try:
        with create_session() as session:
            ProviderRepository(session).sync(providers)
            SourceRepository(session).sync(sources)
            session.commit()
            operation_id = OperationCommandService(session).enqueue_source_catalog_refresh(
                plan, trigger="cli"
            )
    except ValueError as exc:
        typer.echo(f"无法创建目录刷新任务：{exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(f"已创建来源目录刷新任务：{operation_id}")


@sources_app.command("refresh-recover-abandoned")
def recover_abandoned_catalog_refresh(
    operation_id: Annotated[int, typer.Argument(min=1)],
    confirm_abandoned: Annotated[bool, typer.Option("--confirm-abandoned")] = False,
) -> None:
    """After confirming an old Worker stopped, clone only its stuck members into a new batch."""
    with create_session() as session:
        try:
            recovery_id = OperationCommandService(session).recover_abandoned_source_catalog_refresh(
                operation_id, trigger="cli", confirm_abandoned=confirm_abandoned
            )
        except ValueError as error:
            if str(error) == "confirm_abandoned_required":
                typer.echo(
                    "安全优先：请先确认旧 Worker 已停止，并传入 --confirm-abandoned。", err=True
                )
            else:
                typer.echo(str(error), err=True)
            raise typer.Exit(2) from None
    typer.echo(f"已创建仅包含已确认遗弃成员的重试批次：{recovery_id}")


def _load_catalog_refresh_operation(operation_id: int):
    with create_session() as session:
        operation = session.get(OperationRunRecord, operation_id)
        if operation is None or operation.operation_type != "source_catalog_refresh":
            raise LookupError("catalog_refresh_operation_not_found")
        members = list(
            session.scalars(
                select(SourceCatalogRefreshMemberRecord)
                .where(SourceCatalogRefreshMemberRecord.operation_run_id == operation_id)
                .order_by(SourceCatalogRefreshMemberRecord.source_id)
            )
        )
    return operation, members


@sources_app.command("refresh-status")
def show_catalog_refresh_status(operation_id: int) -> None:
    """Read status only; it neither queues work nor performs network I/O."""
    try:
        operation, members = _load_catalog_refresh_operation(operation_id)
    except LookupError:
        typer.echo("未找到来源目录刷新任务", err=True)
        raise typer.Exit(2) from None
    summary = summarize_catalog_members(members)
    total = operation.progress_total if operation.progress_total is not None else len(members)
    typer.echo(f"来源目录刷新任务 {operation.id}：{operation.status}")
    typer.echo(f"完成度：{operation.progress_current}/{total}")
    lanes = (("content", "内容通道"), ("capability", "能力通道"), ("catalog", "目录通道"))
    for lane, label in lanes:
        typer.echo(f"{label}：{summary['lanes'].get(lane, 0)}")
    state_order = (
        "pending",
        "running",
        "succeeded",
        "blocked",
        "degraded",
        "failed",
        "cancelled",
    )
    state_counts = [
        f"{state}：{summary['states'][state]}"
        for state in state_order
        if state in summary["states"]
    ]
    if state_counts:
        typer.echo("成员状态：" + "，".join(state_counts))
    if summary["result_codes"]:
        typer.echo(
            "结果码："
            + "，".join(f"{code}={count}" for code, count in summary["result_codes"].items())
        )


@sources_app.command("refresh-report")
def write_catalog_refresh_report(
    operation_id: int,
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Write a scrubbed Chinese Markdown report for one frozen batch only."""
    try:
        operation, members = _load_catalog_refresh_operation(operation_id)
    except LookupError:
        typer.echo("未找到来源目录刷新任务", err=True)
        raise typer.Exit(2) from None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_catalog_refresh_report(operation, members), encoding="utf-8")
    except OSError:
        typer.echo("catalog_refresh_report_write_failed", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"已生成来源目录刷新报告：{output}")


@sources_app.command("reconcile")
def reconcile_source_catalog(
    root: RootOption = Path("sources"),
    apply: Annotated[bool, typer.Option("--apply")] = False,
) -> None:
    """Plan, then optionally archive database targets absent from the reviewed YAML catalog."""
    sources = load_source_tree(root)
    with create_session() as session:
        plan = build_reconcile_plan(session, {source.id for source in sources})
        typer.echo(
            f"Catalog reconcile: yaml={plan.yaml_count} current_db={plan.current_db_count} "
            f"archive={len(plan.archive_ids)} restore={len(plan.restore_ids)} "
            f"blocked={len(plan.blocked_ids)}"
        )
        if plan.archive_ids:
            typer.echo("Archive candidates: " + ", ".join(plan.archive_ids))
        if plan.restore_ids:
            typer.echo("Restore candidates: " + ", ".join(plan.restore_ids))
        if plan.blocked_ids:
            typer.echo("Blocked by active operation: " + ", ".join(plan.blocked_ids))
        if not apply:
            return
        try:
            apply_reconcile_plan(session, plan)
        except CatalogReconcileBlocked as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from None
        session.commit()
    typer.echo("Catalog reconciliation applied without deleting history")


async def _probe_sources(
    selected,
    persist: bool,
    remediation_acquisition_probe_id: int | None = None,
    max_concurrency: int = 8,
):
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await ProbeRunner(
            ProbeFactory(client), max_concurrency=max_concurrency
        ).probe_all(selected)
    if persist:
        with create_session() as session:
            repository = SourceRepository(session)
            repository.sync(selected)
            for result in results.values():
                repository.save_probe_result(
                    result,
                    remediation_acquisition_probe_id=remediation_acquisition_probe_id,
                )
            session.commit()
    return results


def _build_health_wave_plan(sources):
    source_ids = {source.id for source in sources}
    latest: dict[str, HealthProbeState] = {}
    with create_session() as session:
        rows = session.scalars(
            select(SourceProbeRunRecord)
            .where(SourceProbeRunRecord.source_id.in_(source_ids))
            .order_by(SourceProbeRunRecord.finished_at.desc(), SourceProbeRunRecord.id.desc())
        )
        for row in rows:
            latest.setdefault(row.source_id, HealthProbeState(row.outcome, row.access_kind))
    return select_health_wave(sources, latest, SettingsCredentials().configured_names())


@sources_app.command("health-wave")
def source_health_wave(
    root: RootOption = Path("sources"),
    execute: Annotated[bool, typer.Option("--execute")] = False,
    concurrency: Annotated[int, typer.Option(min=1, max=16)] = 8,
    output: Annotated[Path, typer.Option("--output")] = Path("reports/source-health-v1-2.md"),
) -> None:
    """Plan or execute a bounded recovery probe wave for safe current sources."""
    plan = _build_health_wave_plan(load_source_tree(root))
    results = None
    if execute and plan.candidates:
        results = asyncio.run(
            _probe_sources(
                [candidate.source for candidate in plan.candidates],
                True,
                max_concurrency=concurrency,
            )
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_health_wave_report(plan, results), encoding="utf-8")
    typer.echo(
        f"Health wave: candidates={len(plan.candidates)} "
        f"mode={'executed' if execute else 'plan'} report={output}"
    )


@sources_app.command("probe")
def probe_sources(
    source_id: Annotated[str | None, typer.Argument()] = None,
    root: RootOption = Path("sources"),
    all_sources: Annotated[bool, typer.Option("--all")] = False,
    persist: Annotated[bool, typer.Option("--persist/--no-persist")] = True,
    report_output: Annotated[Path | None, typer.Option("--report-output")] = None,
    remediation_acquisition_probe_id: Annotated[
        int | None, typer.Option("--remediation-acquisition-probe-id", min=1)
    ] = None,
) -> None:
    sources = load_source_tree(root)
    if all_sources:
        selected = sources
    elif source_id:
        selected = [source for source in sources if source.id == source_id]
        if not selected:
            typer.echo(f"Unknown source id: {source_id}")
            raise typer.Exit(2)
    else:
        typer.echo("Provide a source id or --all")
        raise typer.Exit(2)
    if remediation_acquisition_probe_id is not None:
        if all_sources or source_id is None or len(selected) != 1 or not persist:
            typer.echo("Remediation content linkage requires one persisted source probe")
            raise typer.Exit(2)
        with create_session() as session:
            acquisition = session.get(
                SourceAcquisitionProbeRunRecord, remediation_acquisition_probe_id
            )
            candidate = (
                session.get(SourceAcquisitionCandidateRecord, acquisition.candidate_id)
                if acquisition is not None
                else None
            )
            if candidate is None or candidate.source_id != source_id:
                typer.echo("Remediation acquisition probe does not belong to this source")
                raise typer.Exit(2)
    results = asyncio.run(
        _probe_sources(selected, persist)
        if remediation_acquisition_probe_id is None
        else _probe_sources(selected, persist, remediation_acquisition_probe_id)
    )
    for source in selected:
        result = results[source.id]
        typer.echo(
            f"{source.id}: {result.outcome.value} completeness={result.field_completeness:.0%} "
            f"status={result.suggested_status.value} reason={result.reason}"
        )
    if report_output:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(render_source_report(selected, results), encoding="utf-8")
        typer.echo(f"Wrote live source report to {report_output}")


@sources_app.command("report")
def report_sources(
    root: RootOption = Path("sources"),
    output: Annotated[Path, typer.Option("--output")] = Path("reports/source-intelligence.md"),
) -> None:
    sources = load_source_tree(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_source_report(sources), encoding="utf-8")
    typer.echo(f"Wrote source report to {output}")


@sources_app.command("mixed-report")
def report_mixed_sources(
    output: Annotated[Path, typer.Option("--output")] = Path("reports/high-value-mixed-sources.md"),
) -> None:
    """输出高价值混合来源的目录、运行证据和下一步中文报告。"""
    with create_session() as session:
        dashboard = _build_mixed_source_dashboard(session)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_mixed_wave_report(dashboard), encoding="utf-8")
    typer.echo(f"Wrote mixed source health report to {output}")


def _build_mixed_source_dashboard(session):
    # CLI 基础导入不能把 FastAPI 等 Web 运行时作为硬依赖加载。
    from newsradar.web.mixed_source_queries import MixedSourceQueryService

    return MixedSourceQueryService(session).build()


@sources_app.command("close-coverage")
def close_source_coverage(
    root: RootOption = Path("sources"),
    execute: Annotated[bool, typer.Option("--execute/--no-execute")] = False,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
    max_items: Annotated[int, typer.Option("--max-items", min=1, max=5)] = 5,
    output: Annotated[Path, typer.Option("--output")] = Path(
        "reports/source-coverage-closure-v1.md"
    ),
) -> None:
    """Plan or execute bounded trial fetches for uncovered ready direct sources."""
    if wait and not execute:
        typer.echo("--wait 必须与 --execute 一起使用")
        raise typer.Exit(2)

    sources = load_source_tree(root)
    if not execute:
        with create_session() as session:
            plan = CoverageClosureService(session).plan(sources)
        typer.echo(_coverage_plan_summary(plan))
        typer.echo("仅预览，未写入数据库、未创建抓取任务。")
        return

    with create_session() as session:
        repository = SourceRepository(session)
        repository.sync(sources)
        session.commit()
        service = CoverageClosureService(session)
        before = service.plan(sources)
        before_evidence = service.evidence(COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS)
        operations = service.enqueue(
            before,
            max_items=max_items,
            trigger=COVERAGE_CLOSURE_TRIGGER,
        )
        for operation in operations:
            if operation.operation_id:
                typer.echo(f"已创建操作 {operation.operation_id}：{operation.source_id}")
            else:
                typer.echo(f"未创建操作：{operation.source_id}（{operation.status}）")
        if not wait:
            typer.echo("任务已入队，未等待终态；未生成验收报告。")
            return
        terminals = service.wait(operations)
        after = service.plan(sources)
        operation_ids = [
            operation.operation_id for operation in terminals if operation.operation_id
        ]
        after_evidence = service.evidence(
            COVERAGE_CLOSURE_V1_BASELINE_SOURCE_IDS,
            operation_ids=operation_ids,
        )

    for operation in terminals:
        typer.echo(f"操作 {operation.operation_id}：{operation.status}")
    report = render_coverage_closure_report(
        before=before,
        after=after,
        operations=terminals,
        before_evidence=before_evidence,
        after_evidence=after_evidence,
        adjustments=(
            CatalogAdjustment(
                source_id="qwen3-releases",
                conclusion="退出就绪直连统计",
                evidence="官方 Releases 端点当前没有条目，HTTP 200 空数组不算内容覆盖。",
                next_action="官方仓库出现 Release 后重新探测。",
            ),
        ),
        generated_at=datetime.now(UTC),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    typer.echo(f"已写入来源覆盖收口报告：{output}")
    failure_statuses = {
        "enqueue_failed",
        "operation_in_progress",
        "failed",
        "cancelled",
        "partial",
        "interrupted",
        "timed_out",
        "missing",
    }
    if any(operation.status in failure_statuses for operation in terminals):
        raise typer.Exit(1)


def _coverage_plan_summary(plan) -> str:
    return (
        f"范围内：{len(plan.entries)}；已覆盖：{len(plan.covered)}；"
        f"可入队：{len(plan.queueable)}；阻塞：{len(plan.blocked)}"
    )


@remediate_app.command("snapshot")
def snapshot_source_remediation(
    baseline_at: Annotated[str, typer.Option("--baseline-at")],
    output: Annotated[Path, typer.Option("--output")] = Path(
        "reports/source-failure-remediation.md"
    ),
    root: RootOption = Path("sources"),
) -> None:
    """Persist and write an immutable failure batch for one UTC baseline."""
    parsed_baseline = _parse_utc_baseline(baseline_at)
    sources = load_source_tree(root)
    with create_session() as session:
        manifest = RemediationRepository(session).freeze_manifest(parsed_baseline, sources)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_remediation_report(manifest), encoding="utf-8")
    typer.echo(f"已写入 {len(manifest.entries)} 个失败来源的修复清单：{output}")


@remediate_app.command("report")
def report_source_remediation(
    baseline_at: Annotated[str, typer.Option("--baseline-at")],
    output: Annotated[Path, typer.Option("--output")] = Path(
        "reports/source-failure-remediation.md"
    ),
    root: RootOption = Path("sources"),
) -> None:
    """Regenerate the read-only remediation report for the given baseline."""
    parsed_baseline = _parse_utc_baseline(baseline_at)
    sources = load_source_tree(root)
    try:
        with create_session() as session:
            manifest = RemediationRepository(session).enriched_manifest(parsed_baseline, sources)
    except ValueError as error:
        if str(error) != "remediation_batch_not_frozen":
            raise
        typer.echo("该基线尚未冻结；请先运行 newsradar sources remediate snapshot。", err=True)
        raise typer.Exit(code=2) from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_remediation_report(manifest), encoding="utf-8")
    typer.echo(f"已写入 {len(manifest.entries)} 个失败来源的最终修复报告：{output}")


@remediate_app.command("queue")
def queue_source_remediation(
    source_id: Annotated[str, typer.Argument()],
    candidate_key: Annotated[str, typer.Argument()],
    original_probe_id: Annotated[int, typer.Option("--original-probe-id", min=1)],
    baseline_at: Annotated[str, typer.Option("--baseline-at")],
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
) -> None:
    """Queue exactly one audited candidate; only Worker performs network I/O."""
    parsed_baseline = _parse_utc_baseline(baseline_at)
    with create_session() as session:
        commands = OperationCommandService(session)
        try:
            operation_id = commands.enqueue_source_remediation(
                source_id=source_id,
                candidate_key=candidate_key,
                original_probe_id=original_probe_id,
                baseline_at=parsed_baseline,
                trigger="cli",
            )
        except ValueError as error:
            typer.echo(str(error))
            raise typer.Exit(2) from None
        typer.echo(f"已排队来源修复操作：{operation_id}")
        if wait:
            terminal = commands.wait_for_terminal(operation_id)
            typer.echo(f"操作 {operation_id}：{terminal.status}")
            if terminal.status not in {"succeeded", "partial"}:
                raise typer.Exit(1)


@remediate_app.command("retry")
def retry_source_remediation(
    operation_id: Annotated[int, typer.Argument(min=1)],
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = False,
) -> None:
    """Explicitly retry one eligible transient remediation, at most once."""
    with create_session() as session:
        commands = OperationCommandService(session)
        try:
            retry_id = commands.retry_source_remediation(operation_id, trigger="cli")
        except ValueError as error:
            typer.echo(str(error))
            raise typer.Exit(2) from None
        typer.echo(f"已排队一次性修复重试：{retry_id}")
        if wait:
            terminal = commands.wait_for_terminal(retry_id)
            typer.echo(f"操作 {retry_id}：{terminal.status}")
            if terminal.status not in {"succeeded", "partial"}:
                raise typer.Exit(1)


def _research_report(root: Path, provider_root: Path):
    return audit_source_catalog(
        tuple(load_provider_tree(provider_root)), tuple(load_source_tree(root))
    )


def _echo_research_findings(report) -> int:
    labels = {"error": "错误", "warning": "警告", "info": "提示"}
    for finding in report.findings:
        typer.echo(f"[{labels[finding.severity]}] {finding.code}: {finding.message_zh}")
    return sum(finding.severity == "error" for finding in report.findings)


@research_app.command("validate")
def validate_source_research(
    root: RootOption = Path("sources"),
    provider_root: Annotated[
        Path, typer.Option("--provider-root", exists=True, file_okay=False, resolve_path=True)
    ] = Path("providers"),
) -> None:
    report = _research_report(root, provider_root)
    errors = _echo_research_findings(report)
    typer.echo(f"研究审计完成：{report.target_count} 个真实 Target，{errors} 个错误。")
    if errors:
        raise typer.Exit(1)


@research_app.command("audit")
def audit_source_research(
    root: RootOption = Path("sources"),
    provider_root: Annotated[
        Path, typer.Option("--provider-root", exists=True, file_okay=False, resolve_path=True)
    ] = Path("providers"),
) -> None:
    report = _research_report(root, provider_root)
    errors = _echo_research_findings(report)
    pending = report.status_counts.get("needs_research", 0)
    verified = report.status_counts.get("verified", 0)
    typer.echo(f"研究审计：待研究 {pending} 个，已验证 {verified} 个。")
    if errors:
        raise typer.Exit(1)


@research_app.command("report")
def report_source_research(
    root: RootOption = Path("sources"),
    provider_root: Annotated[
        Path, typer.Option("--provider-root", exists=True, file_okay=False, resolve_path=True)
    ] = Path("providers"),
    output: Annotated[Path, typer.Option("--output")] = Path("reports/source-research-v3.md"),
) -> None:
    report = _research_report(root, provider_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_research_report(report), encoding="utf-8")
    errors = _echo_research_findings(report)
    typer.echo(f"已写入来源研究报告：{output}")
    if errors:
        raise typer.Exit(1)


@research_app.command("probe")
def probe_source_research_candidate(
    source_id: Annotated[str, typer.Argument()],
    candidate_key: Annotated[str, typer.Option("--candidate")],
    limit: Annotated[int, typer.Option(min=1, max=5)] = 5,
    video_ids: Annotated[list[str] | None, typer.Option("--video-id")] = None,
    persist: Annotated[bool, typer.Option("--persist/--no-persist")] = True,
    root: RootOption = Path("sources"),
) -> None:
    """执行有界、只读的研究样本，不修改档案或采集开关。"""
    bounded_video_ids = tuple(video_ids or ())
    if len(bounded_video_ids) > 5 or any(
        re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) is None for video_id in bounded_video_ids
    ):
        typer.echo("视频 ID 必须是最多五个、每个 11 位的 YouTube 视频 ID")
        raise typer.Exit(2)
    source = next((item for item in load_source_tree(root) if item.id == source_id), None)
    if source is None:
        typer.echo(f"未知来源：{source_id}")
        raise typer.Exit(2)
    candidate = next(
        (item for item in source.research.candidates if item.key == candidate_key), None
    )
    if candidate is None:
        typer.echo(f"未知研究候选：{candidate_key}")
        raise typer.Exit(2)

    async def run_probe():
        async with research_probe_for(source, candidate) as probe:
            if source.provider_id == "youtube":
                return await probe.probe(source, candidate, limit, bounded_video_ids)
            return await probe.probe(source, candidate, limit)

    result = asyncio.run(run_probe())
    typer.echo(
        f"{source.id}/{candidate.key}: {result.outcome.value} "
        f"样本={len(result.samples)} 说明={result.reason_zh}"
    )
    if persist:
        try:
            with create_session() as session:
                repository = SourceRepository(session)
                record = next(
                    (
                        row
                        for row in repository.current_acquisition_candidates(source.id)
                        if row.candidate_key == candidate.key
                    ),
                    None,
                )
                if record is None:
                    raise RuntimeError("candidate_not_synced")
                repository.save_acquisition_probe_run(
                    candidate_id=record.id,
                    started_at=result.started_at,
                    completed_at=result.finished_at,
                    outcome=result.outcome.value,
                    sample_count=result.sample_count,
                    http_status=result.http_status,
                    latency_ms=result.latency_ms,
                    fields_present=result.fields_present,
                    latest_published_at=result.latest_published_at,
                    schema_fingerprint=result.schema_fingerprint,
                    error_code=result.error_code,
                    details=result.model_dump(mode="json"),
                )
                session.commit()
        except Exception:
            typer.echo("探测结果未持久化（数据库不可用）；可使用 --no-persist 输出内存报告")
    if result.error_code:
        typer.echo(f"代码：{result.error_code}")


@sources_app.command("coverage")
def source_coverage(
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    root: RootOption = Path("sources"),
    provider_root: Annotated[
        Path, typer.Option("--provider-root", exists=True, file_okay=False, resolve_path=True)
    ] = Path("providers"),
    output: Annotated[Path, typer.Option("--output")] = Path("reports/source-coverage.md"),
    history: Annotated[bool, typer.Option("--history/--no-history")] = False,
) -> None:
    providers = load_provider_tree(provider_root)
    sources = load_source_tree(root)
    if provider:
        providers = [item for item in providers if item.id == provider]
        sources = [item for item in sources if item.provider_id == provider]
        if not providers:
            typer.echo(f"Unknown provider id: {provider}")
            raise typer.Exit(2)
    results = None
    if history:
        with create_session() as session:
            results = ProviderRepository(session).latest_probes()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_coverage_report(providers, sources, results), encoding="utf-8")
    typer.echo(f"Wrote source coverage report to {output}")
