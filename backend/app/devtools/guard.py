"""Công cụ dev: bật theo ENV; route /devtools/* không vào OpenAPI và bị gỡ khi ENV không phải dev / smoke."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.settings import Settings

DEV_ENVS = frozenset({"dev", "smoke"})
DEVTOOLS_PATH = "/devtools/"
DEVTOOLS_NAMESPACE = "devtools"


def devtools_enabled(settings: Settings) -> bool:
    return settings.ENV.strip().lower() in DEV_ENVS


def guard_devtools_routes(app: FastAPI, settings: Settings) -> None:
    keep = devtools_enabled(settings)
    routes = []
    for route in app.router.routes:
        if isinstance(route, APIRoute) and DEVTOOLS_PATH in route.path:
            if not keep:
                continue
            route.include_in_schema = False
        routes.append(route)
    app.router.routes[:] = routes
