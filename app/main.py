"""Composition root + lifespan -- wires settings, registry, telemetry,
health cache, and auth together, same shape as naas-api's app/main.py.
"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.clusters import router as clusters_router
from app.auth import build_auth
from app.core.config import get_settings
from app.health import build_health_checker
from app.health.cache import HealthCache
from app.registry.file_source import FileRegistrySource
from app.telemetry import build_telemetry

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level)

    http_client = httpx.AsyncClient()

    registry = FileRegistrySource(settings.registry_path)
    telemetry = build_telemetry(settings, http_client)
    health_checker = build_health_checker(settings, http_client)
    health_cache = HealthCache(health_checker, registry, settings.health_check_interval_seconds)
    auth = build_auth(settings)

    app.state.settings = settings
    app.state.registry = registry
    app.state.telemetry = telemetry
    app.state.health_cache = health_cache
    app.state.auth = auth
    app.state.http_client = http_client

    await health_cache.start()

    yield

    await health_cache.stop()
    await http_client.aclose()


app = FastAPI(title="naas-discovery", lifespan=lifespan)
app.include_router(clusters_router)


@app.get("/healthz")
async def healthz():
    """naas-discovery's own liveness -- not to be confused with §9's health
    module, which checks *other* clusters' naas-api instances.
    """
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(title=app.title, version="0.1.0", routes=app.routes)

    scheme_name, scheme = app.state.auth.openapi_scheme()
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[scheme_name] = scheme
    # Only /api/v1/* requires auth (§3) -- /healthz, /readyz, /docs don't.
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/api/v1"):
            continue
        for operation in operations.values():
            if isinstance(operation, dict):
                operation["security"] = [{scheme_name: []}]

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
