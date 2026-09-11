"""Application settings, loaded from CLUSTER_* environment variables.

Same pydantic-settings pattern as naas-api's app/core/config.py, but with
env_prefix="CLUSTER_" instead of naas-api's "APP_" -- see docs/design for
why. Field names stay unprefixed; the prefix only ever comes from
env_prefix, so it appears exactly once in the resulting env var name.
"""

import json
from functools import lru_cache
from typing import Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RecommendationMode = Literal["priority", "metrics", "hybrid"]
RecommendationPrecedence = Literal["priority", "telemetry"]
TelemetryModule = Literal["none", "prometheus", "native_api"]
FailurePolicy = Literal["fail_open", "fail_closed"]
HealthModule = Literal["none", "http"]
AuthModule = Literal["basic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLUSTER_", env_file=".env", extra="ignore")

    app_name: str = "naas-discovery"
    log_level: str = "INFO"

    # Registry (§2): the static YAML file listing every cluster.
    registry_path: str = "/etc/naas-discovery/clusters.yaml"

    # Recommendation (§7): how the "recommended" entry in GET /clusters is chosen.
    recommendation_mode: RecommendationMode = "priority"
    recommendation_precedence: RecommendationPrecedence = "priority"
    capacity_threshold: Optional[float] = None

    # Telemetry / capacity module (§8).
    telemetry_module: TelemetryModule = "none"
    telemetry_config_path: str = "/etc/naas-discovery/telemetry.yaml"
    telemetry_failure_policy: FailurePolicy = "fail_open"

    # Health module (§9) -- on by default, deliberately.
    health_module: HealthModule = "http"
    health_check_interval_seconds: int = 30
    health_check_timeout_seconds: int = 3

    # Auth (§10) -- vendored from naas-api, same shape.
    auth_module: AuthModule = "basic"
    basic_auth_users: dict[str, str] = {}
    basic_auth_users_file: Optional[str] = None

    @field_validator("basic_auth_users", mode="before")
    @classmethod
    def parse_users(cls, value):
        # Allow the users map to be passed as a JSON string (env var), same
        # convention as naas-api.
        if isinstance(value, str):
            value = value.strip()
            return json.loads(value) if value else {}
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
