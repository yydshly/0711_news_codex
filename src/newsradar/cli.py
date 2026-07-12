from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import httpx
import typer

from newsradar.db.session import create_session
from newsradar.local_postgres import (
    LocalPostgresError,
    build_local_postgres_manager,
)
from newsradar.providers.probes import probe_providers
from newsradar.providers.reporting import render_coverage_report
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.sources.probes.factory import ProbeFactory
from newsradar.sources.probes.runner import ProbeRunner
from newsradar.sources.reporting import render_source_report
from newsradar.sources.repository import SourceRepository
from newsradar.sources.yaml_loader import load_source_tree

app = typer.Typer(help="News Codex source intelligence registry")
sources_app = typer.Typer(help="Validate, sync, probe, and report audited sources")
providers_app = typer.Typer(help="Validate, sync, probe, and report source providers")
db_app = typer.Typer(help="Manage the project-local PostgreSQL runtime")
app.add_typer(sources_app, name="sources")
app.add_typer(providers_app, name="providers")
app.add_typer(db_app, name="db")

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


@app.command("web")
def run_web(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8765,
) -> None:
    import uvicorn

    from newsradar.web import create_app

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


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
