from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import select_autoescape
from sqlalchemy.exc import OperationalError, ProgrammingError
from starlette.templating import Jinja2Templates

from newsradar.db.session import create_session
from newsradar.web.diagnostics import build_diagnostic_narrative
from newsradar.web.queries import DashboardQueryService

ServiceFactory = Callable[[], AbstractContextManager[DashboardQueryService]]
_WEB_ROOT = Path(__file__).resolve().parent
_UNDEFINED_TABLE_SQLSTATE = "42P01"

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


def _active_filters(**values: object) -> dict[str, object]:
    return {key: value for key, value in values.items() if value not in (None, "")}


def _normalized_query(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()[:100]


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


def create_app(service_factory: ServiceFactory | None = None) -> FastAPI:
    resolved_service_factory = service_factory or _dashboard_service_context
    app = FastAPI(title="News Codex 来源感知台", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=_WEB_ROOT / "templates")
    templates.env.autoescape = select_autoescape(("html", "xml"), default_for_string=True)
    app.mount("/static", StaticFiles(directory=_WEB_ROOT / "static"), name="static")

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
        return templates.TemplateResponse(
            request=request,
            name="not_found.html",
            status_code=404,
        )

    @app.get("/", response_class=HTMLResponse)
    def dashboard_shell(request: Request) -> HTMLResponse:
        try:
            with resolved_service_factory() as service:
                summary = service.summary()
                providers = service.providers()
                probes = service.probes()
                gaps = service.gap_groups()
                diagnostic = build_diagnostic_narrative(summary, providers, gaps)
        except OperationalError:
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "error_title": "数据库暂时不可用",
                    "error_message": "请先启动 News Codex 的本地数据库，然后刷新页面。",
                    "recovery_command": "uv run newsradar db start",
                    "database_status": "数据库连接失败",
                    "database_status_tone": "failed",
                },
                status_code=503,
            )
        except ProgrammingError as error:
            if not _is_undefined_table(error):
                return templates.TemplateResponse(
                    request=request,
                    name="error.html",
                    context={
                        "error_title": "数据库查询失败",
                        "error_message": "本地数据库未能完成只读查询，请检查状态后重试。",
                        "database_status": "数据库查询失败",
                        "database_status_tone": "failed",
                    },
                    status_code=503,
                )
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "error_title": "数据库尚未完成迁移",
                    "error_message": "请先创建所需的数据表，然后刷新页面。",
                    "recovery_command": "uv run alembic upgrade head",
                    "database_status": "数据库等待迁移",
                    "database_status_tone": "blocked",
                },
                status_code=503,
            )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "summary": summary,
                "diagnostic": diagnostic,
                "recent_probes": probes[:10],
                "top_gaps": gaps[:5],
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
            },
        )

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
        with resolved_service_factory() as service:
            rows = service.providers(filters)
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
            },
        )

    @app.get("/providers/{provider_id}", response_class=HTMLResponse)
    def provider_details(request: Request, provider_id: str) -> HTMLResponse:
        with resolved_service_factory() as service:
            detail = service.provider_detail(provider_id)
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="provider_detail.html",
            context={
                "provider": detail,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
            },
        )

    @app.get("/targets", response_class=HTMLResponse)
    def target_catalog(
        request: Request,
        provider_id: str | None = None,
        target_type: Annotated[TargetType | None, Query()] = None,
        coverage_mode: Annotated[CoverageMode | None, Query()] = None,
        availability: Annotated[Availability | None, Query()] = None,
        q: str | None = None,
    ) -> HTMLResponse:
        filters = _active_filters(
            provider_id=provider_id,
            target_type=target_type,
            coverage_mode=coverage_mode,
            availability=availability,
            q=_normalized_query(q),
        )
        with resolved_service_factory() as service:
            rows = service.targets(filters)
        return templates.TemplateResponse(
            request=request,
            name="targets.html",
            context={
                "targets": rows,
                "filters": filters,
                "target_type_options": _TARGET_TYPES,
                "coverage_options": _COVERAGE_MODES,
                "availability_options": _AVAILABILITIES,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
            },
        )

    @app.get("/targets/{source_id}", response_class=HTMLResponse)
    def target_details(request: Request, source_id: str) -> HTMLResponse:
        with resolved_service_factory() as service:
            detail = service.target_detail(source_id)
        if detail is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="target_detail.html",
            context={
                "target": detail,
                "database_status": "数据库已连接",
                "database_status_tone": "healthy",
            },
        )

    return app
