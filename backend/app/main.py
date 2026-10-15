"""FastAPI app factory cho process `api`. Chạy: `bw api` (uvicorn factory)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.api_google import router as google_router
from app.core.cid import CID_HEADER
from app.core.connections.registry import close_connections, init_connections
from app.core.exception_handlers import register_exception_handlers
from app.core.http_log import HttpLogMiddleware
from app.core.http_rules import HttpLogRules
from app.core.httpx_log import install_httpx_logging
from app.core.logging import configure_logging, get_logger
from app.core.messaging.runtime import start_messaging, stop_messaging
from app.core.operations.registry import namespaces
from app.core.operations.rest import build_operation_router
from app.core.operations.runner import check_operations
from app.core.redact import build_keys
from app.core.settings import ROOT_DIR, Settings, get_settings, use_settings
from app.devtools.guard import DEVTOOLS_NAMESPACE, devtools_enabled, guard_devtools_routes
from app.domains import domain_for_path, load_domains
from app.observability import close_observability, init_observability
from app.system.health import router as health_router

logger = get_logger(__name__)
OPENAPI_FILE = ROOT_DIR / "frontend" / "src" / "lib" / "api" / "openapi.json"


def create_app(settings: Settings | None = None, *, connect: bool = True) -> FastAPI:
    s = settings or get_settings()
    rules = HttpLogRules.from_file(s.resolve_path(s.LOG_HTTP_RULES_FILE))  # sai file rule → dừng ngay
    keys = build_keys(s.extra_redact_keys)
    use_settings(s)
    load_domains()
    check_operations()  # cấu hình operation sai (vd agent=True thiếu toolset) → không boot

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging("api", s)
        install_httpx_logging(rules, keys, log=s.LOG_HTTP_OUT)  # log tắt được; bắt raw (trace) luôn chạy
        defaults = [
            name
            for name, missing in (
                ("BUILD_VERSION", s.BUILD_VERSION == "dev"),
                ("MONGO", not s.MONGO_ENABLED),
                ("LOG_HTTP_RULES_FILE", not s.LOG_HTTP_RULES_FILE),
            )
            if missing
        ]
        logger.info(
            "khởi động %s env=%s version=%s mongo=%s DEFAULTS_APPLIED=%s",
            s.SERVICE_NAME,
            s.ENV,
            s.BUILD_VERSION,
            "on" if s.MONGO_ENABLED else "off",
            defaults,
            extra={"loc": "boot0001"},
        )  # R11: giá trị hiệu lực + phần đang dùng mặc định + rule log HTTP mặc định
        if connect:
            app.state.conns = await init_connections("api", s)
            await init_observability(s, app.state.conns.mongo)
            await start_messaging(s, "api")
        logger.info("api sẵn sàng", extra={"loc": "boot0002"})
        try:
            yield
        finally:
            logger.info("tắt %s", s.SERVICE_NAME, extra={"loc": "boot0003"})
            if connect:
                await stop_messaging()
                await close_observability()
                await close_connections()

    app = FastAPI(
        title=s.PROJECT_NAME,
        debug=s.DEBUG,
        lifespan=lifespan,
        docs_url=f"{s.api_prefix}/docs",
        openapi_url=f"{s.api_prefix}/openapi.json",
        redoc_url=None,
    )
    app.state.settings = s
    app.state.conns = None
    register_exception_handlers(app)
    app.include_router(health_router, prefix=s.api_prefix)
    app.include_router(google_router, prefix=s.api_prefix)
    for namespace in namespaces(app_only=True):  # chỉ operation khai trong app.* (miền giả của test không lọt — Q5)
        is_dev_tool = namespace == DEVTOOLS_NAMESPACE
        if is_dev_tool and not devtools_enabled(s):
            continue  # registry có thể đã nạp devtools trong cùng process — ENV này không cho
        router = build_operation_router(namespace)
        app.include_router(router, prefix=s.api_prefix, include_in_schema=not is_dev_tool)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.CORS_ALLOW_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
        expose_headers=[CID_HEADER],
    )
    # Thêm SAU CORS → nằm ngoài cùng: log cả preflight, cid có trên mọi response.
    app.add_middleware(
        HttpLogMiddleware,
        settings=s,
        rules=rules,
        enabled=s.LOG_HTTP_IN,
        resolve_module=lambda path: domain_for_path(path, s.api_prefix),
    )
    guard_devtools_routes(app, s)
    return app


def render_openapi(settings: Settings) -> str:
    """OpenAPI của app `api` — sắp khoá, thụt 2, xuống dòng cuối: diff ổn định cho file hợp đồng (R7)."""
    doc = create_app(settings, connect=False).openapi()
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
