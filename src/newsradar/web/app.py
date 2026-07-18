from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated, Literal, TypeVar
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import select_autoescape
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from newsradar.credentials import SettingsCredentials
from newsradar.daily_reports.autopilot_repository import DailyAutopilotRepository
from newsradar.daily_reports.repository import DailyReportRepository
from newsradar.daily_reports.schema import (
    DailyReportEditorialReviewDraft,
    DailyReportOverviewEditorialReviewDraft,
)
from newsradar.db.models import (
    DailyReportAudioArtifactRecord,
    OperationRunRecord,
    SourceDefinitionRecord,
)
from newsradar.db.session import create_session
from newsradar.diagnostics import collect_diagnostic_snapshot, create_diagnostic_bundle
from newsradar.operations.commands import OperationCommandService
from newsradar.operations.repository import OperationRepository
from newsradar.providers.repository import ProviderRepository
from newsradar.providers.yaml_loader import load_provider_tree
from newsradar.settings import get_settings
from newsradar.sources.catalog_refresh import build_catalog_refresh_plan
from newsradar.sources.probes.base import ProbeOutcome as DomainProbeOutcome
from newsradar.sources.repository import SourceRepository
from newsradar.sources.yaml_loader import load_source_tree
from newsradar.waves.loader import load_wave_profile
from newsradar.waves.planning import build_wave_plan
from newsradar.web.capability_queries import CatalogSnapshot, load_catalog_snapshot
from newsradar.web.daily_autopilot_queries import DailyAutopilotQueryService
from newsradar.web.daily_report_queries import DailyReportQueryService
from newsradar.web.event_merge_queries import EventMergeQueryService
from newsradar.web.event_queries import EventQueryService
from newsradar.web.i18n import format_datetime_zh, format_duration_ms, zh_label
from newsradar.web.item_queries import ItemQueryService
from newsradar.web.mixed_source_queries import MixedSourceQueryService
from newsradar.web.operation_queries import OperationQueryService
from newsradar.web.queries import DashboardQueryService
from newsradar.web.routes.system import build_minimax_runtime_view, build_system_health
from newsradar.web.security import (
    UnsafeWrite,
    consume_one_time_token,
    require_loopback_host,
    require_same_origin,
)
from newsradar.web.source_wave_queries import SourceWaveQueryService

ServiceFactory = Callable[[], AbstractContextManager[DashboardQueryService]]
CatalogFactory = Callable[[], CatalogSnapshot]
_WEB_ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
_UNDEFINED_TABLE_SQLSTATE = "42P01"
_DAILY_REPORT_AUDIO_ROOT = Path(".local/daily-report-audio")

ProviderCategory = Literal[
    "social_community",
    "professional_media",
    "first_party",
    "aggregator_search",
    "research_developer",
    "newsletter_podcast",
    "trend_business",
]
Availability = Literal[
    "ready",
    "requires_credentials",
    "requires_approval",
    "requires_payment",
    "manual_only",
    "unavailable",
]
CostTier = Literal["free", "free_quota", "freemium", "paid", "enterprise", "unknown"]
TargetType = Literal[
    "publisher_feed",
    "account",
    "channel",
    "keyword",
    "topic",
    "community",
    "search_query",
    "trend",
    "market",
]
CoverageMode = Literal["direct", "indirect", "catalog_only"]
EventVisibilityMode = Literal["current", "legacy"]
EventScopeMode = Literal["latest", "current_catalog", "catalog"]
EventTierMode = Literal["hotspot", "signal", "audit_only"]
ProbeType = Literal["capability", "content"]
QueryResult = TypeVar("QueryResult")
PROBE_OUTCOME_VALUES = tuple(outcome.value for outcome in DomainProbeOutcome)

_DAILY_REPORT_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_daily_report_window": (422, "时间窗口仅支持 24、48 或 72 小时。"),
    "complete_event_snapshot_required": (409, "尚无完整事件运行快照，请先完成事件构建。"),
    "ambiguous_event_snapshot_versions": (
        409,
        "事件运行快照包含冲突版本，暂时无法生成日报。",
    ),
    "invalid_daily_report_move": (422, "移动方向只能是上移或下移。"),
    "daily_report_not_found": (404, "日报不存在。"),
    "daily_report_item_not_found": (404, "日报条目不存在或不属于当前日报。"),
    "daily_report_overview_item_not_found": (
        404,
        "全览条目不存在或不属于当前日报。",
    ),
    "daily_report_archived": (409, "该日报已归档，不能再修改。"),
    "daily_report_must_be_archived": (409, "仅已归档的日报可以创建修订版。"),
    "daily_report_revision_conflict": (409, "日报修订发生冲突，请刷新页面后重试。"),
    "invalid_daily_report_editorial_decision": (
        422,
        "审核结论仅支持保留、待补证、排除或合并重复。",
    ),
    "invalid_daily_report_editorial_title": (
        422,
        "中文标题不能为空且不能超过 240 个字符。",
    ),
    "invalid_daily_report_editorial_summary": (
        422,
        "中文文章概述不能为空且不能超过 4000 个字符。",
    ),
    "invalid_daily_report_editorial_recommendation": (
        422,
        "中文审核建议不能为空且不能超过 2000 个字符。",
    ),
    "invalid_daily_report_editorial_evidence_assessment": (
        422,
        "中文证据评价不能为空且不能超过 2000 个字符。",
    ),
    "daily_report_text_corrupted": (
        422,
        "检测到疑似编码损坏的连续问号，请修正中文内容后再继续。",
    ),
    "invalid_daily_report_overview_duplicate_target": (
        422,
        "重复项必须关联同一日报中的另一条全览情报。",
    ),
    "invalid_daily_report_overview_duplicate_self": (
        422,
        "重复项不能关联自身。",
    ),
    "daily_report_overview_review_incomplete": (
        409,
        "情报全览仍有未审核条目，暂不能生成全览语音。",
    ),
    "daily_report_overview_has_no_included_items": (
        409,
        "情报全览没有可播报的保留或需补证条目。",
    ),
    "active_daily_autopilot_exists": (409, "已有自动日报正在执行，请先查看当前任务。"),
}

_PROVIDER_CATEGORIES = (
    ("social_community", "社交与社区"),
    ("professional_media", "专业媒体"),
    ("first_party", "第一方来源"),
    ("aggregator_search", "聚合与搜索"),
    ("research_developer", "研究与开发者"),
    ("newsletter_podcast", "新闻简报与播客"),
    ("trend_business", "趋势与商业"),
)
_AVAILABILITIES = (
    ("ready", "可直接使用"),
    ("requires_credentials", "需要凭据"),
    ("requires_approval", "需要审批"),
    ("requires_payment", "需要付费"),
    ("manual_only", "仅限手动"),
    ("unavailable", "不可用"),
)
_COST_TIERS = (
    ("free", "免费"),
    ("free_quota", "免费额度"),
    ("freemium", "基础免费"),
    ("paid", "付费"),
    ("enterprise", "企业版"),
    ("unknown", "未知"),
)
_TARGET_TYPES = (
    ("publisher_feed", "发布方订阅源"),
    ("account", "账号"),
    ("channel", "频道"),
    ("keyword", "关键词"),
    ("topic", "主题"),
    ("community", "社区"),
    ("search_query", "搜索查询"),
    ("trend", "趋势"),
    ("market", "市场"),
)
_COVERAGE_MODES = (
    ("direct", "直接覆盖"),
    ("indirect", "间接发现"),
    ("catalog_only", "仅目录收录"),
)
_PROBE_TYPES = (("capability", "能力探测"), ("content", "内容探测"))
_PROBE_OUTCOMES = tuple((outcome, zh_label("outcome", outcome)) for outcome in PROBE_OUTCOME_VALUES)


def _active_filters(**values: object) -> dict[str, object]:
    return {key: value for key, value in values.items() if value not in (None, "")}


def _normalized_query(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()[:100]


def _daily_report_http_error(error: Exception, *, default_status: int) -> HTTPException:
    error_code = str(error)
    logger.info("daily report request rejected", extra={"error_code": error_code})
    status_code, detail = _DAILY_REPORT_ERRORS.get(
        error_code, (default_status, "日报操作暂时无法完成。")
    )
    return HTTPException(status_code=status_code, detail=detail)


def _daily_report_revision_conflict(error: RuntimeError) -> HTTPException:
    if str(error) != "daily_report_revision_conflict":
        raise error
    return _daily_report_http_error(error, default_status=409)


def _daily_report_audio_path(relative_path: str) -> Path | None:
    root = _DAILY_REPORT_AUDIO_ROOT.resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents:
        return None
    return target


def _source_wave_plan():
    """Load reviewed local definitions only; never probe or open an HTTP client."""
    sources = load_source_tree(Path("sources"))
    providers = load_provider_tree(Path("providers"))
    return build_catalog_refresh_plan(
        sources,
        providers,
        latest={},
        configured_credentials=SettingsCredentials().configured_names(),
    )


def _high_value_wave_plan(session):
    """Synchronize reviewed local definitions then freeze one local-only WavePlan.

    This boundary deliberately uses persisted probe history only.  It never creates an
    HTTP client, reads a browser session, or invokes MiniMax.
    """
    profile = load_wave_profile(Path("wave_profiles/high-value-ai-tech.yaml"))
    sources = load_source_tree(Path("sources"))
    providers = load_provider_tree(Path("providers"))
    ProviderRepository(session).sync(providers)
    SourceRepository(session).sync(sources)
    session.commit()
    repository = SourceRepository(session)
    source_ids = list(profile.source_ids)
    probes = repository.latest_probe_snapshots(source_ids)
    return build_wave_plan(
        profile,
        sources,
        probes,
        SettingsCredentials().configured_names(),
        successful_fetch_access=repository.successful_fetch_access(source_ids),
    )


@contextmanager
def _dashboard_service_context() -> Iterator[DashboardQueryService]:
    session = create_session()
    try:
        yield DashboardQueryService(session)
    finally:
        session.close()


def _is_undefined_table(error: ProgrammingError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    return sqlstate == _UNDEFINED_TABLE_SQLSTATE


def create_app(
    service_factory: ServiceFactory | None = None,
    catalog_factory: CatalogFactory | None = None,
) -> FastAPI:
    resolved_service_factory = service_factory or _dashboard_service_context
    resolved_catalog_factory = catalog_factory or load_catalog_snapshot
    app = FastAPI(title="News Codex 来源感知台", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=token_urlsafe(32),
        same_site="strict",
        https_only=False,
    )
    templates = Jinja2Templates(directory=_WEB_ROOT / "templates")
    templates.env.autoescape = select_autoescape(("html", "xml"), default_for_string=True)
    templates.env.filters["zh_label"] = lambda value, dimension: zh_label(dimension, value)
    templates.env.filters["format_datetime_zh"] = format_datetime_zh
    templates.env.filters["format_duration_ms"] = format_duration_ms
    from newsradar.daily_reports.service import _public_url as daily_report_public_url

    templates.env.filters["daily_report_public_url"] = daily_report_public_url
    templates.env.globals["http_trust_env"] = get_settings().http_trust_env
    app.mount("/static", StaticFiles(directory=_WEB_ROOT / "static"), name="static")

    def database_error_response(request: Request, error: SQLAlchemyError) -> HTMLResponse:
        if isinstance(error, OperationalError):
            context = {
                "error_title": "数据库暂时不可用",
                "error_message": "请先启动 News Codex 的本地数据库，然后刷新页面。",
                "recovery_command": "uv run newsradar db start",
                "database_status": "数据库连接失败",
                "database_status_tone": "failed",
            }
        elif _is_undefined_table(error):
            context = {
                "error_title": "数据库尚未完成迁移",
                "error_message": "请先创建所需的数据表，然后刷新页面。",
                "recovery_command": "uv run alembic upgrade head",
                "database_status": "数据库等待迁移",
                "database_status_tone": "blocked",
            }
        else:
            context = {
                "error_title": "数据库查询失败",
                "error_message": "本地数据库未能完成只读查询，请检查状态后重试。",
                "database_status": "数据库查询失败",
                "database_status_tone": "failed",
            }
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context=context,
            status_code=503,
        )

    def query_service_safely(
        request: Request,
        query: Callable[[DashboardQueryService], QueryResult],
    ) -> tuple[QueryResult | None, HTMLResponse | None]:
        try:
            with resolved_service_factory() as service:
                return query(service), None
        except SQLAlchemyError as error:
            return None, database_error_response(request, error)

    def query_with_timestamp_safely(
        request: Request,
        query: Callable[[DashboardQueryService], QueryResult],
    ) -> tuple[tuple[QueryResult, object] | None, HTMLResponse | None]:
        return query_service_safely(
            request, lambda service: (query(service), service.latest_probe_at())
        )

    def issue_action_token(request: Request) -> str:
        token = token_urlsafe(32)
        tokens = list(request.session.get("tokens", []))[-15:]
        tokens.append(token)
        request.session["tokens"] = tokens
        return token

    def research_query_safely(request: Request, query):
        try:
            return query_with_timestamp_safely(request, query)
        except Exception:
            logger.exception("research page query failed")
            response = templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "error_title": "研究页面暂时不可用",
                    "error_message": "研究查询未能完成，请查看服务日志后重试。",
                    "recovery_command": "",
                    "database_status": "研究页面不可用",
                    "database_status_tone": "failed",
                },
                status_code=503,
            )
            return None, response

    def event_merge_error_response(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "error_title": "事件合并候选暂时不可用",
                "error_message": "候选查询未能安全完成，请查看本地服务日志后重试。",
                "recovery_command": "",
                "database_status": "候选查询失败",
                "database_status_tone": "failed",
            },
            status_code=503,
        )

    async def require_safe_action(request: Request) -> dict[str, str]:
        try:
            require_loopback_host(request.headers.get("host"))
            require_same_origin(
                request.headers.get("origin"),
                request.headers.get("host"),
                fetch_site=request.headers.get("sec-fetch-site"),
            )
            body = (await request.body()).decode("utf-8", errors="replace")
            values = {
                name: entries[-1]
                for name, entries in parse_qs(body, keep_blank_values=True).items()
                if entries
            }
            consume_one_time_token(request.session, values.get("action_token", ""))
            return values
        except UnsafeWrite as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.exception_handler(404)
    async def not_found(request: Request, error: Exception) -> HTMLResponse:
        detail = getattr(error, "detail", None)
        if not isinstance(detail, str) or detail in {"", "Not Found"}:
            detail = "这个本地只读页面尚未提供，或地址有误。"
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            context={"not_found_detail": detail},
            status_code=404,
        )

    def source_dashboard(request: Request) -> HTMLResponse:
        def load_dashboard(service: DashboardQueryService):
            return service.capability_overview(
                resolved_catalog_factory(),
                minimax_configured=bool(get_settings().minimax_api_key),
            )

        dashboard, error_response = query_service_safely(request, load_dashboard)
        if error_response is not None:
            return error_response
        assert dashboard is not None
        return templates.TemplateResponse(
            request=request,
            name="capability_overview.html",
            context={
                "capability": dashboard,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": dashboard.latest_probe_at,
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def events_home(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                event_home = EventQueryService(session).latest_operation_home()
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="events_home.html",
            context={
                "event_home": event_home,
                "action_token": issue_action_token(request),
                "snapshot_unavailable": event_home is None,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/sources", response_class=HTMLResponse)
    def sources(request: Request) -> HTMLResponse:
        return source_dashboard(request)

    @app.get("/mixed-sources", response_class=HTMLResponse)
    def mixed_sources(request: Request) -> HTMLResponse:
        """Show catalog scope and persisted fetch evidence without running a fetch."""
        try:
            with create_session() as session:
                dashboard = MixedSourceQueryService(session).build()
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        latest_run_at = max(
            (
                run.finished_at
                for target in dashboard.targets
                for run in target.recent_runs
                if run.finished_at is not None
            ),
            default=None,
        )
        return templates.TemplateResponse(
            request=request,
            name="mixed_sources.html",
            context={
                "dashboard": dashboard,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_run_at,
            },
        )

    @app.get("/events", response_class=HTMLResponse)
    def events(
        request: Request,
        status: str | None = None,
        category: str | None = None,
        tier: EventTierMode | None = None,
        visibility: EventVisibilityMode = "current",
        scope: EventScopeMode = "latest",
        hours: Annotated[int | None, Query(ge=1, le=8760)] = None,
    ) -> HTMLResponse:
        query_now = datetime.now(UTC)
        filters = _active_filters(
            status=status,
            category=category,
            display_tier=tier,
        )
        if hours is not None:
            filters["hours"] = hours
        try:
            with create_session() as session:
                service = EventQueryService(session)
                if scope == "latest" and visibility == "current":
                    event_page = service.latest_operation_page(filters, now=query_now)
                    snapshot_unavailable = event_page is None
                else:
                    filters["visibility"] = visibility
                    filters["until"] = query_now
                    if hours is not None:
                        filters["since"] = query_now - timedelta(hours=hours)
                    event_page = service.list_events(filters, visibility=visibility)
                    snapshot_unavailable = False
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="events.html",
            context={
                "event_page": event_page,
                "event_scope": scope,
                "snapshot_unavailable": snapshot_unavailable,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/emerging", response_class=HTMLResponse)
    def emerging(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                event_page = EventQueryService(session).latest_operation_page(
                    {"status": "emerging", "limit": 50}
                )
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="emerging.html",
            context={
                "event_page": event_page,
                "snapshot_unavailable": event_page is None,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/daily-reports", response_class=HTMLResponse)
    def daily_reports(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                service = DailyReportQueryService(session)
                reports = service.list_reports()
                snapshot_available = service.has_complete_event_snapshot()
                autopilot_runs = DailyAutopilotQueryService(session).list_recent()
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="daily_reports.html",
            context={
                "reports": reports,
                "snapshot_available": snapshot_available,
                "autopilot_runs": autopilot_runs,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.post("/daily-reports")
    async def generate_daily_report(request: Request) -> RedirectResponse:
        values = await require_safe_action(request)
        from newsradar.daily_reports import DailyReportService

        try:
            try:
                window_hours = int(values.get("window_hours", "24"))
            except (TypeError, ValueError) as error:
                raise HTTPException(
                    status_code=422, detail="时间窗口必须是 24、48 或 72 小时。"
                ) from error
            with create_session() as session:
                report = DailyReportService(session).generate(window_hours)
                report_id = report.id
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=422) from error
        except RuntimeError as error:
            raise _daily_report_revision_conflict(error) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

    @app.post("/daily-reports/autopilot")
    async def enqueue_daily_autopilot(request: Request) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            try:
                window_hours = int(values.get("window_hours", "24"))
            except (TypeError, ValueError) as error:
                raise ValueError("invalid_daily_report_window") from error
            with create_session() as session:
                run_id = OperationCommandService(session).enqueue_daily_autopilot(
                    plan=_source_wave_plan(),
                    window_hours=window_hours,
                    trigger="web",
                )
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=409) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-autopilot/{run_id}", status_code=303)

    @app.get("/daily-autopilot/{run_id}", response_class=HTMLResponse)
    def daily_autopilot_detail(request: Request, run_id: int) -> HTMLResponse:
        try:
            with create_session() as session:
                detail = DailyAutopilotQueryService(session).detail(run_id)
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        if detail is None:
            raise HTTPException(status_code=404, detail="自动日报任务不存在。")
        return templates.TemplateResponse(
            request=request,
            name="daily_autopilot_detail.html",
            context={
                "autopilot": detail,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": detail.updated_at,
            },
        )

    @app.post("/daily-autopilot/{run_id}/cancel")
    async def cancel_daily_autopilot(request: Request, run_id: int) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                runs = DailyAutopilotRepository(session)
                run = runs.get_for_update(run_id)
                for operation_id in (
                    run.source_operation_id,
                    run.event_operation_id,
                    run.decision_audio_operation_id,
                    run.overview_audio_operation_id,
                ):
                    if operation_id is not None:
                        OperationRepository(session).request_cancel(operation_id)
                runs.cancel(run_id)
                session.commit()
        except LookupError as error:
            raise HTTPException(status_code=404, detail="自动日报任务不存在。") from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-autopilot/{run_id}", status_code=303)

    @app.get("/daily-reports/{report_id}", response_class=HTMLResponse)
    def daily_report_detail(request: Request, report_id: int) -> HTMLResponse:
        try:
            with create_session() as session:
                detail = DailyReportQueryService(session).detail(report_id)
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="daily_report_detail.html",
            context={
                "daily_report": detail,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": detail.report.window_end,
            },
        )

    @app.post("/daily-reports/{report_id}/items/{item_id}/included")
    async def set_daily_report_item_included(
        request: Request, report_id: int, item_id: int
    ) -> RedirectResponse:
        values = await require_safe_action(request)
        included_value = values.get("included")
        if included_value not in {"true", "false"}:
            raise HTTPException(status_code=422, detail="收录状态必须明确为 true 或 false。")
        included = included_value == "true"
        try:
            with create_session() as session:
                DailyReportRepository(session).set_included(report_id, item_id, included=included)
        except LookupError as error:
            raise _daily_report_http_error(error, default_status=404) from error
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=409) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

    @app.post("/daily-reports/{report_id}/items/{item_id}/editorial-reviews")
    async def save_daily_report_editorial_review(
        request: Request, report_id: int, item_id: int
    ) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            draft = DailyReportEditorialReviewDraft.create(
                decision=values.get("decision", ""),
                zh_title=values.get("zh_title", ""),
                zh_summary=values.get("zh_summary", ""),
                review_recommendation=values.get("review_recommendation", ""),
                evidence_assessment=values.get("evidence_assessment", ""),
            )
            with create_session() as session:
                DailyReportRepository(session).save_editorial_review(report_id, item_id, draft)
        except LookupError as error:
            raise _daily_report_http_error(error, default_status=404) from error
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=422) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

    @app.post(
        "/daily-reports/{report_id}/overview-items/{item_id}/editorial-reviews"
    )
    async def save_daily_report_overview_editorial_review(
        request: Request, report_id: int, item_id: int
    ) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            draft = DailyReportOverviewEditorialReviewDraft.create(
                decision=values.get("decision", ""),
                zh_title=values.get("zh_title", ""),
                zh_summary=values.get("zh_summary", ""),
                review_recommendation=values.get("review_recommendation", ""),
                evidence_assessment=values.get("evidence_assessment", ""),
                duplicate_of_overview_item_id=values.get(
                    "duplicate_of_overview_item_id", ""
                ),
            )
            with create_session() as session:
                DailyReportRepository(session).save_overview_editorial_review(
                    report_id, item_id, draft
                )
        except LookupError as error:
            raise _daily_report_http_error(error, default_status=404) from error
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=422) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(
            url=f"/daily-reports/{report_id}#overview-item-{item_id}",
            status_code=303,
        )

    @app.post("/daily-reports/{report_id}/items/{item_id}/move")
    async def move_daily_report_item(
        request: Request, report_id: int, item_id: int
    ) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            with create_session() as session:
                DailyReportRepository(session).move_item(
                    report_id, item_id, direction=values.get("direction", "")
                )
        except LookupError as error:
            raise _daily_report_http_error(error, default_status=404) from error
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=409) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

    @app.post("/daily-reports/{report_id}/archive")
    async def archive_daily_report(request: Request, report_id: int) -> RedirectResponse:
        _values = await require_safe_action(request)
        try:
            with create_session() as session:
                OperationCommandService(session).archive_and_enqueue_daily_report_audio(
                    report_id=report_id,
                    trigger="daily_archive",
                )
        except LookupError as error:
            raise _daily_report_http_error(error, default_status=404) from error
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=409) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

    @app.post("/daily-reports/{report_id}/audio/{rendition}")
    async def enqueue_daily_report_audio(
        request: Request, report_id: int, rendition: str
    ) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                OperationCommandService(session).enqueue_daily_report_audio(
                    report_id=report_id, rendition=rendition, trigger="web"
                )
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=422) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{report_id}", status_code=303)

    @app.get("/daily-reports/{report_id}/audio-artifacts/{artifact_id}")
    def daily_report_audio_artifact(report_id: int, artifact_id: int) -> FileResponse:
        with create_session() as session:
            artifact = session.get(DailyReportAudioArtifactRecord, artifact_id)
            if (
                artifact is None
                or artifact.daily_report_id != report_id
                or artifact.status != "succeeded"
                or not artifact.relative_audio_path
            ):
                raise HTTPException(status_code=404, detail="音频文件不存在或尚未生成。")
            target = _daily_report_audio_path(artifact.relative_audio_path)
        if target is None or not target.is_file():
            raise HTTPException(status_code=404, detail="音频文件不存在或尚未生成。")
        return FileResponse(
            target,
            media_type="audio/mpeg",
            filename=f"daily-report-{report_id}.mp3",
        )

    @app.post("/daily-reports/{report_id}/revise")
    async def revise_daily_report(request: Request, report_id: int) -> RedirectResponse:
        _values = await require_safe_action(request)
        from newsradar.daily_reports import DailyReportService

        try:
            with create_session() as session:
                revision = DailyReportService(session).revise(report_id)
                revision_id = revision.id
        except LookupError as error:
            raise _daily_report_http_error(error, default_status=404) from error
        except ValueError as error:
            raise _daily_report_http_error(error, default_status=409) from error
        except RuntimeError as error:
            raise _daily_report_revision_conflict(error) from error
        except SQLAlchemyError as error:
            return database_error_response(request, error)  # type: ignore[return-value]
        return RedirectResponse(url=f"/daily-reports/{revision_id}", status_code=303)

    @app.get("/event-merge-candidates", response_class=HTMLResponse)
    def event_merge_candidates(
        request: Request,
        status: str | None = "pending",
        candidate_type: str | None = None,
        event_id: int | None = None,
        limit: int = 200,
    ) -> HTMLResponse:
        try:
            with create_session() as session:
                service = EventMergeQueryService(session)
                summary = service.summary()
                candidates = service.list_candidates(
                    status,
                    candidate_type,
                    limit=limit,
                    event_id=event_id,
                )
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        except Exception as error:
            logger.error(
                "event merge candidate list query failed",
                extra={"error_type": type(error).__name__},
            )
            return event_merge_error_response(request)
        return templates.TemplateResponse(
            request=request,
            name="event_merge_candidates.html",
            context={
                "summary": summary,
                "candidates": candidates,
                "selected_status": status,
                "selected_type": candidate_type,
                "selected_event_id": event_id,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/event-merge-candidates/{candidate_id}", response_class=HTMLResponse)
    def event_merge_candidate_detail(request: Request, candidate_id: int) -> HTMLResponse:
        try:
            with create_session() as session:
                candidate = EventMergeQueryService(session).get_candidate(candidate_id)
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        except Exception as error:
            logger.error(
                "event merge candidate detail query failed",
                extra={"error_type": type(error).__name__},
            )
            return event_merge_error_response(request)
        if candidate is None:
            raise HTTPException(status_code=404, detail="未找到该事件合并候选。")
        return templates.TemplateResponse(
            request=request,
            name="event_merge_candidate_detail.html",
            context={
                "candidate": candidate,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.post("/event-merge-candidates/scan")
    async def scan_event_merge_candidates(request: Request) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                operation_id = OperationCommandService(session).enqueue_event_merge_scan("web")
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        except ValueError as error:
            logger.info(
                "event merge scan request rejected",
                extra={"error_type": type(error).__name__},
            )
            raise HTTPException(status_code=422, detail="无法创建事件合并候选扫描任务。") from error
        except Exception as error:
            logger.error(
                "event merge scan enqueue failed",
                extra={"error_type": type(error).__name__},
            )
            return event_merge_error_response(request)  # type: ignore[return-value]
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.post("/event-merge-candidates/{candidate_id}/{decision}")
    async def decide_event_merge_candidate(
        request: Request, candidate_id: int, decision: str
    ) -> RedirectResponse:
        await require_safe_action(request)
        if decision not in {"apply", "confirm", "dismiss", "recheck"}:
            raise HTTPException(status_code=422, detail="无效的候选处理动作。")
        try:
            with create_session() as session:
                candidate = EventMergeQueryService(session).get_candidate(candidate_id)
                if candidate is None:
                    raise HTTPException(status_code=404, detail="未找到该事件合并候选。")
                if candidate.status != "pending":
                    raise HTTPException(
                        status_code=409, detail="该候选已处理或已过期，不能重复操作。"
                    )
                if decision not in candidate.allowed_decisions:
                    raise HTTPException(status_code=422, detail="该候选类型不允许此处理动作。")
                operation_id = OperationCommandService(session).enqueue_event_merge_decision(
                    candidate_id, decision, "web"
                )
        except HTTPException:
            raise
        except SQLAlchemyError as error:
            return database_error_response(request, error)
        except ValueError as error:
            logger.info(
                "event merge decision rejected",
                extra={"error_type": type(error).__name__},
            )
            raise HTTPException(status_code=422, detail="无法创建候选处理任务。") from error
        except Exception as error:
            logger.error(
                "event merge decision enqueue failed",
                extra={"error_type": type(error).__name__},
            )
            return event_merge_error_response(request)  # type: ignore[return-value]
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.get("/events/{event_id}", response_class=HTMLResponse)
    def event_detail(
        request: Request,
        event_id: int,
        operation: int | None = None,
        version: int | None = None,
    ) -> HTMLResponse:
        if (operation is None) != (version is None):
            raise HTTPException(status_code=400, detail="operation_and_version_required")
        try:
            with create_session() as session:
                service = EventQueryService(session)
                event_detail = (
                    service.get_operation_event(event_id, operation, version)
                    if operation is not None and version is not None
                    else service.get_event(event_id)
                )
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        if event_detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="event_detail.html",
            context={
                "event_detail": event_detail,
                "action_token": issue_action_token(request),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    async def enqueue_event_action(
        request: Request, event_id: int, action: str, payload: dict[str, object] | None = None
    ) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                if EventQueryService(session).get_event(event_id) is None:
                    raise HTTPException(status_code=404)
                operation_id = OperationCommandService(session).enqueue_event_action(
                    action, event_id, {"actor": "web", **(payload or {})}, "web"
                )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.post("/events/build")
    async def build_events(request: Request) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            window_hours = int(values.get("window_hours", "24"))
            with create_session() as session:
                operation_id = OperationCommandService(session).enqueue_event_pipeline(
                    window_hours=window_hours, trigger="web"
                )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.post("/events/update")
    async def update_high_value_events(request: Request) -> RedirectResponse:
        """Queue exactly one frozen high-value wave; Worker owns all I/O and models."""
        await require_safe_action(request)
        try:
            with create_session() as session:
                plan = _high_value_wave_plan(session)
                operation_id = OperationCommandService(session).enqueue_high_value_wave(
                    plan=plan, trigger="web"
                )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.post("/events/{event_id}/recluster")
    async def recluster_event(request: Request, event_id: int) -> RedirectResponse:
        return await enqueue_event_action(request, event_id, "recluster")

    @app.post("/events/{event_id}/enrich")
    async def enrich_event(request: Request, event_id: int) -> RedirectResponse:
        return await enqueue_event_action(request, event_id, "enrich")

    @app.post("/events/{event_id}/exclude")
    async def exclude_event(request: Request, event_id: int) -> RedirectResponse:
        return await enqueue_event_action(request, event_id, "exclude")

    @app.post("/events/merge")
    async def merge_events(request: Request) -> RedirectResponse:
        await require_safe_action(request)
        raise HTTPException(
            status_code=409,
            detail="禁止按事件编号直接合并；请从事件合并候选页面审查并入队。",
        )

    @app.post("/events/{event_id}/split")
    async def split_event(request: Request, event_id: int) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            member_ids = [
                int(value) for value in values.get("member_ids", "").split(",") if value.strip()
            ]
            if event_id <= 0 or not member_ids or any(value <= 0 for value in member_ids):
                raise ValueError("split requires non-empty positive member ids")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        # Reuse the durable action boundary; scope remains auditable and worker-owned.
        try:
            with create_session() as session:
                operation_id = OperationCommandService(session).enqueue_event_action(
                    "split", event_id, {"member_ids": member_ids, "actor": "web"}, "web"
                )
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.get("/providers", response_class=HTMLResponse)
    def provider_catalog(
        request: Request,
        category: Annotated[ProviderCategory | None, Query()] = None,
        availability: Annotated[Availability | None, Query()] = None,
        cost_tier: Annotated[CostTier | None, Query()] = None,
        q: str | None = None,
    ) -> HTMLResponse:
        filters = _active_filters(
            category=category,
            availability=availability,
            cost_tier=cost_tier,
            q=_normalized_query(q),
        )

        result, error_response = query_with_timestamp_safely(
            request, lambda service: service.providers(filters)
        )
        if error_response is not None:
            return error_response
        assert result is not None
        rows, latest_probe_at = result
        return templates.TemplateResponse(
            request=request,
            name="providers.html",
            context={
                "providers": rows,
                "filters": filters,
                "category_options": _PROVIDER_CATEGORIES,
                "availability_options": _AVAILABILITIES,
                "cost_options": _COST_TIERS,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/research", response_class=HTMLResponse)
    def research_dashboard(request: Request) -> HTMLResponse:
        result, error_response = research_query_safely(
            request, lambda service: service.research_targets()
        )
        if error_response is not None:
            return error_response
        targets, latest_probe_at = result or ((), None)
        return templates.TemplateResponse(
            request=request,
            name="research_dashboard.html",
            context={
                "targets": targets,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/remediation", response_class=HTMLResponse)
    def remediation_console(
        request: Request,
        category: str | None = Query(default=None),
        provider_id: str | None = Query(default=None),
        conclusion: str | None = Query(default=None),
    ) -> HTMLResponse:
        """Read-only view of the newest immutable failed-source batch."""
        result, error_response = research_query_safely(
            request,
            lambda service: service.remediation_dashboard(
                category=category,
                provider_id=provider_id,
                conclusion=conclusion,
            ),
        )
        if error_response is not None:
            return error_response
        dashboard, latest_probe_at = result or (None, None)
        return templates.TemplateResponse(
            request=request,
            name="remediation.html",
            context={
                "dashboard": dashboard,
                "selected_category": category or "",
                "selected_provider": provider_id or "",
                "selected_conclusion": conclusion or "",
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/research/targets/{source_id}", response_class=HTMLResponse)
    def research_target(request: Request, source_id: str) -> HTMLResponse:
        result, error_response = research_query_safely(
            request, lambda service: service.research_target(source_id)
        )
        if error_response is not None:
            return error_response
        detail, latest_probe_at = result or (None, None)
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="research_target.html",
            context={
                "target": detail,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/providers/{provider_id}", response_class=HTMLResponse)
    def provider_details(request: Request, provider_id: str) -> HTMLResponse:
        result, error_response = query_with_timestamp_safely(
            request, lambda service: service.provider_detail(provider_id)
        )
        if error_response is not None:
            return error_response
        assert result is not None
        detail, latest_probe_at = result
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="provider_detail.html",
            context={
                "provider": detail,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/targets", response_class=HTMLResponse)
    def target_catalog(
        request: Request,
        provider_id: str | None = None,
        target_type: Annotated[TargetType | None, Query()] = None,
        coverage_mode: Annotated[CoverageMode | None, Query()] = None,
        availability: Annotated[Availability | None, Query()] = None,
        free_direct: bool = False,
        three_success: bool = False,
        q: str | None = None,
        catalog_state: str = "current",
    ) -> HTMLResponse:
        filters = _active_filters(
            provider_id=provider_id,
            target_type=target_type,
            coverage_mode=coverage_mode,
            availability=availability,
            free_direct=True if free_direct else None,
            three_success=True if three_success else None,
            q=_normalized_query(q),
            catalog_state=catalog_state if catalog_state in {"current", "archived"} else "current",
        )
        result, error_response = query_with_timestamp_safely(
            request,
            lambda service: (
                service.targets(filters),
                service.target_conclusion_summary(),
            ),
        )
        if error_response is not None:
            return error_response
        assert result is not None
        payload, latest_probe_at = result
        rows, conclusion_summary = payload
        return templates.TemplateResponse(
            request=request,
            name="targets.html",
            context={
                "targets": rows,
                "conclusion_summary": conclusion_summary,
                "filters": filters,
                "target_type_options": _TARGET_TYPES,
                "coverage_options": _COVERAGE_MODES,
                "availability_options": _AVAILABILITIES,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/targets/{source_id}", response_class=HTMLResponse)
    def target_details(request: Request, source_id: str) -> HTMLResponse:
        result, error_response = query_with_timestamp_safely(
            request, lambda service: service.target_detail(source_id)
        )
        if error_response is not None:
            return error_response
        assert result is not None
        detail, latest_probe_at = result
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="target_detail.html",
            context={
                "target": detail,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/probes", response_class=HTMLResponse)
    def probe_history(
        request: Request,
        probe_type: Annotated[ProbeType | None, Query()] = None,
        outcome: Annotated[DomainProbeOutcome | None, Query()] = None,
        provider_id: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> HTMLResponse:
        filters = _active_filters(
            probe_type=probe_type,
            outcome=outcome.value if outcome else None,
            provider_id=_normalized_query(provider_id),
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size,
        )
        result, error_response = query_with_timestamp_safely(
            request, lambda service: service.probes(filters)
        )
        if error_response is not None:
            return error_response
        assert result is not None
        rows, latest_probe_at = result
        return templates.TemplateResponse(
            request=request,
            name="probes.html",
            context={
                "probes": rows,
                "filters": filters,
                "probe_type_options": _PROBE_TYPES,
                "outcome_options": _PROBE_OUTCOMES,
                "has_content_probe": any(row.probe_type == "content" for row in rows),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
                "page": page,
                "page_size": page_size,
            },
        )

    @app.get("/gaps", response_class=HTMLResponse)
    def coverage_gaps(request: Request) -> HTMLResponse:
        result, error_response = query_with_timestamp_safely(
            request, lambda service: service.gap_groups()
        )
        if error_response is not None:
            return error_response
        assert result is not None
        groups, latest_probe_at = result
        return templates.TemplateResponse(
            request=request,
            name="gaps.html",
            context={
                "gap_groups": groups,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": latest_probe_at,
            },
        )

    @app.get("/operations", response_class=HTMLResponse)
    def operations(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                rows = OperationQueryService(session).list_recent()
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="operations.html",
            context={
                "operations": rows,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
                "action_token": issue_action_token(request),
            },
        )

    @app.get("/source-waves", response_class=HTMLResponse)
    def source_waves(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                waves = SourceWaveQueryService(session).list_waves()
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        active_wave = next((wave for wave in waves if wave.status in {"queued", "running"}), None)
        return templates.TemplateResponse(
            request=request,
            name="source_waves.html",
            context={
                "waves": waves,
                "active_wave": active_wave,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
                "action_token": issue_action_token(request),
            },
        )

    @app.post("/source-waves")
    async def enqueue_source_wave(request: Request) -> RedirectResponse:
        await require_safe_action(request)
        try:
            plan = _source_wave_plan()
            with create_session() as session:
                operation_id = OperationCommandService(session).enqueue_source_catalog_refresh(
                    plan, trigger="web"
                )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/source-waves/{operation_id}", status_code=303)

    @app.get("/source-waves/{operation_id}", response_class=HTMLResponse)
    def source_wave_detail(
        request: Request,
        operation_id: int,
        lane: str | None = None,
        provider_id: str | None = None,
        availability: str | None = None,
        coverage_mode: str | None = None,
        state: str | None = None,
        result_code: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> HTMLResponse:
        try:
            with create_session() as session:
                detail = SourceWaveQueryService(session).detail(
                    operation_id,
                    lane=lane,
                    provider_id=provider_id,
                    availability=availability,
                    coverage_mode=coverage_mode,
                    state=state,
                    result_code=result_code,
                    page=page,
                    page_size=page_size,
                )
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="source_wave_detail.html",
            context={
                "wave": detail,
                "filters": _active_filters(
                    lane=lane,
                    provider_id=provider_id,
                    availability=availability,
                    coverage_mode=coverage_mode,
                    state=state,
                    result_code=result_code,
                ),
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
                "action_token": issue_action_token(request),
            },
        )

    @app.post("/source-waves/{operation_id}/cancel")
    async def cancel_source_wave(request: Request, operation_id: int) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                operation = session.get(OperationRunRecord, operation_id)
                if operation is None or operation.operation_type != "source_catalog_refresh":
                    raise HTTPException(status_code=404)
                if not OperationCommandService(session).cancel(operation_id):
                    raise HTTPException(status_code=409, detail="operation cannot be cancelled")
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/source-waves/{operation_id}", status_code=303)

    @app.post("/source-waves/{operation_id}/retry")
    async def retry_source_wave(request: Request, operation_id: int) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                try:
                    retry_id = OperationCommandService(session).retry_source_catalog_refresh(
                        operation_id, trigger="web"
                    )
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/source-waves/{retry_id}", status_code=303)

    @app.post("/source-waves/{operation_id}/recover-abandoned")
    async def recover_abandoned_source_wave(
        request: Request, operation_id: int
    ) -> RedirectResponse:
        values = await require_safe_action(request)
        try:
            with create_session() as session:
                try:
                    retry_id = OperationCommandService(
                        session
                    ).recover_abandoned_source_catalog_refresh(
                        operation_id,
                        trigger="web",
                        confirm_abandoned=values.get("confirm_abandoned") == "true",
                    )
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/source-waves/{retry_id}", status_code=303)

    @app.post("/operations/fetch")
    async def enqueue_fetch(request: Request) -> RedirectResponse:
        values = await require_safe_action(request)
        source_id = values.get("source_id", "").strip()
        if not source_id:
            raise HTTPException(status_code=422, detail="source_id is required")
        try:
            with create_session() as session:
                source_exists = session.scalar(
                    select(SourceDefinitionRecord.id).where(SourceDefinitionRecord.id == source_id)
                )
                if source_exists is None:
                    raise HTTPException(status_code=422, detail="unknown source_id")
                operation_id = OperationCommandService(session).enqueue_fetch(
                    source_id=source_id,
                    provider=None,
                    dry_run=False,
                    max_items=None,
                    one_off=False,
                    trigger="web",
                )
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.get("/operations/{operation_id}", response_class=HTMLResponse)
    def operation_detail(request: Request, operation_id: int) -> HTMLResponse:
        try:
            with create_session() as session:
                detail = OperationQueryService(session).get(operation_id)
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="operation_detail.html",
            context={
                "operation_detail": detail,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
                "action_token": issue_action_token(request),
            },
        )

    @app.post("/operations/{operation_id}/cancel")
    async def cancel_operation(request: Request, operation_id: int) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                if not OperationCommandService(session).cancel(operation_id):
                    raise HTTPException(status_code=409, detail="operation cannot be cancelled")
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/operations/{operation_id}", status_code=303)

    @app.post("/operations/{operation_id}/retry")
    async def retry_operation(request: Request, operation_id: int) -> RedirectResponse:
        await require_safe_action(request)
        try:
            with create_session() as session:
                try:
                    retry_id = OperationCommandService(session).retry(operation_id, trigger="web")
                except ValueError as error:
                    raise HTTPException(status_code=409, detail=str(error)) from error
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url=f"/operations/{retry_id}", status_code=303)

    @app.get("/fetch-runs", response_class=HTMLResponse)
    def fetch_runs(request: Request, source_id: str | None = None) -> HTMLResponse:
        try:
            with create_session() as session:
                rows = ItemQueryService(session).list_fetch_runs(source_id=source_id)
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="fetch_runs.html",
            context={
                "fetch_runs": rows,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/items", response_class=HTMLResponse)
    def raw_items(
        request: Request, source_id: str | None = None, q: str | None = None
    ) -> HTMLResponse:
        try:
            with create_session() as session:
                page = ItemQueryService(session).list_items(
                    source_id=source_id, title_query=_normalized_query(q)
                )
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="items.html",
            context={
                "item_page": page,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/items/{raw_item_id}", response_class=HTMLResponse)
    def raw_item_detail(request: Request, raw_item_id: int) -> HTMLResponse:
        try:
            with create_session() as session:
                item = ItemQueryService(session).get_item(raw_item_id)
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        if item is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="item_detail.html",
            context={
                "item": item,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
            },
        )

    @app.get("/duplicates", response_class=HTMLResponse)
    def duplicates(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                rows = ItemQueryService(session).list_duplicate_candidates()
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return templates.TemplateResponse(
            request=request,
            name="duplicates.html",
            context={
                "duplicates": rows,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
                "action_token": issue_action_token(request),
            },
        )

    @app.post("/duplicates/{duplicate_id}/{decision}")
    async def review_duplicate(
        request: Request, duplicate_id: int, decision: Literal["confirm", "dismiss"]
    ) -> RedirectResponse:
        await require_safe_action(request)
        status = "confirmed" if decision == "confirm" else "dismissed"
        try:
            with create_session() as session:
                if not ItemQueryService(session).review_duplicate(duplicate_id, status):
                    raise HTTPException(status_code=409, detail="duplicate cannot be reviewed")
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return RedirectResponse(url="/duplicates", status_code=303)

    @app.get("/system", response_class=HTMLResponse)
    def system_health(request: Request) -> HTMLResponse:
        try:
            with create_session() as session:
                health = build_system_health(session)
                minimax_runtime = build_minimax_runtime_view(session, get_settings())
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        configured_credentials = SettingsCredentials().configured_names()
        credential_statuses = tuple(
            (name, "已配置" if name in configured_credentials else "未配置")
            for name in (
                "GITHUB_TOKEN",
                "REDDIT_CLIENT_ID",
                "REDDIT_CLIENT_SECRET",
                "YOUTUBE_API_KEY",
            )
        )
        return templates.TemplateResponse(
            request=request,
            name="system.html",
            context={
                "health": health,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
                "latest_probe_at": None,
                "action_token": issue_action_token(request),
                "credential_statuses": credential_statuses,
                "minimax_runtime": minimax_runtime,
            },
        )

    @app.post("/system/diagnostics")
    async def create_system_diagnostic(request: Request):  # type: ignore[no-untyped-def]
        try:
            await require_safe_action(request)
        except UnsafeWrite as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        try:
            with create_session() as session:
                snapshot = collect_diagnostic_snapshot(session)
            archive = create_diagnostic_bundle(Path(".local/diagnostics"), snapshot)
        except (OperationalError, ProgrammingError) as error:
            return database_error_response(request, error)
        return {"archive": str(archive), "scrubbed": True}

    return app
