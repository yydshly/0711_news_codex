from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import select_autoescape
from sqlalchemy.exc import OperationalError, ProgrammingError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.templating import Jinja2Templates

from newsradar.db.session import create_session
from newsradar.web.queries import DashboardQueryService

ServiceFactory = Callable[[], AbstractContextManager[DashboardQueryService]]
_WEB_ROOT = Path(__file__).resolve().parent


@contextmanager
def _dashboard_service_context() -> Iterator[DashboardQueryService]:
    session = create_session()
    try:
        yield DashboardQueryService(session)
    finally:
        session.close()


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

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> HTMLResponse:
        if error.status_code != 404:
            raise error
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
        except OperationalError:
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "error_title": "数据库暂时不可用",
                    "error_message": "请先启动 News Codex 的本地数据库，然后刷新页面。",
                    "recovery_command": "uv run newsradar db start",
                },
                status_code=503,
            )
        except ProgrammingError:
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "error_title": "数据库尚未完成迁移",
                    "error_message": "请先创建所需的数据表，然后刷新页面。",
                    "recovery_command": "uv run alembic upgrade head",
                },
                status_code=503,
            )
        return templates.TemplateResponse(
            request=request,
            name="base.html",
            context={"summary": summary, "database_status": "数据库已连接"},
        )

    return app
