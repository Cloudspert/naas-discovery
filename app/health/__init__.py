"""Pluggable health-check modules. Register new ones in HEALTH_MODULES."""

import httpx

from app.core.config import Settings
from app.health.base import HealthChecker
from app.health.http import HttpHealthChecker
from app.health.noop import NoopHealthChecker

__all__ = ["HealthChecker", "HttpHealthChecker", "NoopHealthChecker", "build_health_checker", "HEALTH_MODULES"]

# Each factory takes (settings, shared_http_client) -- the client is owned
# and closed by main.py's lifespan, not by the checker/provider itself.
HEALTH_MODULES = {
    "none": lambda settings, client: NoopHealthChecker(),
    "http": lambda settings, client: HttpHealthChecker(settings.health_check_timeout_seconds, client),
}


def build_health_checker(settings: Settings, client: httpx.AsyncClient) -> HealthChecker:
    if settings.health_module not in HEALTH_MODULES:
        raise ValueError(f"unknown health module '{settings.health_module}'")
    return HEALTH_MODULES[settings.health_module](settings, client)
