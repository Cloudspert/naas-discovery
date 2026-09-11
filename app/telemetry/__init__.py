"""Pluggable telemetry/capacity modules. Register new ones in TELEMETRY_MODULES."""

import httpx

from app.core.config import Settings
from app.telemetry.base import CapacityProvider
from app.telemetry.config import load_telemetry_config
from app.telemetry.native_api import NativeAPICapacityProvider
from app.telemetry.noop import NoopCapacityProvider
from app.telemetry.prometheus import PrometheusCapacityProvider

__all__ = [
    "CapacityProvider",
    "NoopCapacityProvider",
    "PrometheusCapacityProvider",
    "NativeAPICapacityProvider",
    "build_telemetry",
    "TELEMETRY_MODULES",
]

# Each factory takes (settings, shared_http_client) -- the client is owned
# and closed by main.py's lifespan, not by the provider itself.
TELEMETRY_MODULES = {
    "none": lambda settings, client: NoopCapacityProvider(),
    "prometheus": lambda settings, client: PrometheusCapacityProvider(
        load_telemetry_config(settings.telemetry_config_path), client
    ),
    "native_api": lambda settings, client: NativeAPICapacityProvider(),
}


def build_telemetry(settings: Settings, client: httpx.AsyncClient) -> CapacityProvider:
    if settings.telemetry_module not in TELEMETRY_MODULES:
        raise ValueError(f"unknown telemetry module '{settings.telemetry_module}'")
    return TELEMETRY_MODULES[settings.telemetry_module](settings, client)
