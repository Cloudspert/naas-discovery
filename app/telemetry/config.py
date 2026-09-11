"""Loads telemetry.yaml (§8): Prometheus URL, PromQL template, and the
optional name-glob `overrides` that let different clusters use different
Prometheus instances / credentials / queries.

telemetry.yaml is Secret-mounted, not a ConfigMap, because it can carry
plaintext `username`/`password` -- see the design doc §8 and §12.
"""

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from app.core.errors import ConfigError


class TelemetryOverride(BaseModel):
    name: str  # glob pattern matched against cluster id, e.g. "CAS-DEV-*"
    prometheus_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    capacity_query: Optional[str] = None


class TelemetryConfig(BaseModel):
    prometheus_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    capacity_query: Optional[str] = None
    overrides: list[TelemetryOverride] = []


@dataclass
class ResolvedTelemetry:
    """The effective (post-override) settings for one cluster."""

    prometheus_url: Optional[str]
    username: Optional[str]
    password: Optional[str]
    capacity_query: Optional[str]


def load_telemetry_config(path: str) -> TelemetryConfig:
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigError(f"telemetry config file not found: {file_path}")

    with file_path.open() as f:
        raw = yaml.safe_load(f) or {}

    return TelemetryConfig.model_validate(raw)


def resolve_for_cluster(config: TelemetryConfig, cluster_id: str) -> ResolvedTelemetry:
    """Find the first override whose glob `name` matches `cluster_id`
    (evaluated top to bottom, first match wins -- §8), and fill in any
    field it doesn't set from the top-level default.
    """
    match = next((o for o in config.overrides if fnmatch(cluster_id, o.name)), None)

    def pick(field: str):
        override_value = getattr(match, field) if match else None
        return override_value if override_value is not None else getattr(config, field)

    return ResolvedTelemetry(
        prometheus_url=pick("prometheus_url"),
        username=pick("username"),
        password=pick("password"),
        capacity_query=pick("capacity_query"),
    )
