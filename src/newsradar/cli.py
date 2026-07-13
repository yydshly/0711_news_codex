from __future__ import annotations

import asyncio
import os
import re
import socket
import time
from pathlib import Path
from typing import Annotated

import httpx
import typer

from newsradar.db.models import OperationRunRecord
from newsradar.db.session import create_session
from newsradar.diagnostics import collect_diagnostic_snapshot, create_diagnostic_bundle
from newsradar.events.runtime import EventOperationHandler
from newsradar.local_postgres import (
    LocalPostgresError,
    build_local_postgres_manager,
)
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.fetch_runtime import FetchOperationHandler
from newsradar.operations.repository import OperationRepository
from newsradar.operations.router import OperationRouter
from newsradar.operations.worker import Worker
from newsradar.providers.probes import probe_providers
from newsradar.providers.reporting import render_coverage_report
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.research.audit import audit_source_catalog
from newsradar.research.probes.youtube import YouTubeResearchProbe
from newsradar.research.reporting import render_research_report
from newsradar.runtime import RuntimeSupervisor
from newsradar.settings import get_settings
from newsradar.sources.probes.factory import ProbeFactory
from newsradar.sources.probes.runner import ProbeRunner
from newsradar.sources.reporting import render_source_report
from newsradar.sources.repository import SourceRepository
from newsradar.sources.yaml_loader import load_source_tree

app = typer.Typer(help="News Codex source intelligence registry")
sources_app = typer.Typer(help="Validate, sync, probe, and report audited sources")
research_app = typer.Typer(help="只读来源研究审计")
providers_app = typer.Typer(help="Validate, sync, probe, and report source providers")
db_app = typer.Typer(help="Manage the project-local PostgreSQL runtime")
app.add_typer(sources_app, name="sources")
sources_app.add_typer(research_app, name="research")
app.add_typer(providers_app, name="providers")
app.add_typer(db_app, name="db")
operations_app = typer.Typer(help="Inspect and retry durable operations")
app.add_typer(operations_app, name="operations")
events_app = typer.Typer(help="Build and inspect durable event intelligence")
app.add_typer(events_app, name="events")
diagnostics_app = typer.Typer(help="Create scrubbed local runtime diagnostics")
app.add_typer(diagnostics_app, name="diagnostics")

RootOption = Annotated[
    Path, typer.Option("--root", exists=True, file_okay=False, resolve_path=True)
]
ProviderRootOption = Annotated[
    Path, typer.Option("--root", exists=True, file_okay=False, resolve_path=True)
]


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
        typer.Option("--password", prompt=True, hide_input=True),
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


@app.command("fetch")
def fetch_sources(
    source_id: Annotated[str | None, typer.Argument()] = None,
    root: RootOption = Path("sources"),
    approved: Annotated[bool, typer.Option("--approved")] = True,
    one_off: Annotated[bool, typer.Option("--one-off")] = False,
    provider: Annotated[str | None, typer.Option()] = None,
    max_items: Annotated[int | None, typer.Option(min=1)] = None,
    dry_run: Annotated[bool, typer.Option()] = False,
    wait: Annotated[bool, typer.Option("--wait/--no-wait")] = True,
) -> None:
    """Queue audited source fetches; only a Worker performs network work."""
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
    worker_id: Annotated[str | None, typer.Option()] = None,
    once: Annotated[bool, typer.Option("--once/--forever")] = False,
    poll_seconds: Annotated[float, typer.Option(min=0.1, max=60.0)] = 1.0,
) -> None:
    """Consume durable operations; network work only occurs in this process."""
    sources = load_source_tree(root)
    handler = OperationRouter(
        {
            "fetch": FetchOperationHandler.production(sources),
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


@app.command("serve")
def serve() -> None:
    """Start the local Web UI and durable Worker together."""
    exit_code = RuntimeSupervisor().run()
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


async def _probe_sources(selected, persist: bool):
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await ProbeRunner(ProbeFactory(client)).probe_all(selected)
    if persist:
        with create_session() as session:
            repository = SourceRepository(session)
            repository.sync(selected)
            for result in results.values():
                repository.save_probe_result(result)
            session.commit()
    return results


@sources_app.command("probe")
def probe_sources(
    source_id: Annotated[str | None, typer.Argument()] = None,
    root: RootOption = Path("sources"),
    all_sources: Annotated[bool, typer.Option("--all")] = False,
    persist: Annotated[bool, typer.Option("--persist/--no-persist")] = True,
    report_output: Annotated[Path | None, typer.Option("--report-output")] = None,
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
    results = asyncio.run(_probe_sources(selected, persist))
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
    if source.provider_id != "youtube":
        typer.echo("当前仅支持 YouTube 研究样本")
        raise typer.Exit(2)

    async def run_probe():
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0), trust_env=False
        ) as client:
            from newsradar.ingestion.fetchers.base import HttpPolicy

            return await YouTubeResearchProbe(HttpPolicy(client)).probe(
                source, candidate, limit, bounded_video_ids
            )

    result = asyncio.run(run_probe())
    typer.echo(
        f"{source.id}/{candidate.key}: {result.outcome.value} "
        f"样本={len(result.samples)} 说明={result.reason_zh}"
    )
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
