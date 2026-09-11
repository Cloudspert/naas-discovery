"""Pluggable authentication. HTTP Basic today; add more modules in AUTH_MODULES.

Same AUTH_MODULES registry pattern as naas-api. The one addition beyond
naas-api's own app/auth/__init__.py is _load_basic_auth_users below, which
implements CLUSTER_BASIC_AUTH_USERS_FILE (§10) -- a YAML file alternative
to the CLUSTER_BASIC_AUTH_USERS env var, for mounting the Secret as a
volume instead of flattening it into env vars. This lives here (not in
BasicAuth itself) so BasicAuth stays identical to naas-api's copy.
"""

import yaml

from app.auth.base import AuthError, Principal
from app.auth.basic import BasicAuth
from app.core.config import Settings
from app.core.errors import ConfigError

__all__ = ["AuthError", "Principal", "BasicAuth", "build_auth", "AUTH_MODULES"]


def _load_basic_auth_users(settings: Settings) -> dict[str, str]:
    if not settings.basic_auth_users_file:
        return settings.basic_auth_users

    try:
        with open(settings.basic_auth_users_file) as f:
            users = yaml.safe_load(f) or {}
    except OSError as exc:
        raise ConfigError(f"could not read basic_auth_users_file: {exc}") from exc

    if not isinstance(users, dict):
        raise ConfigError(
            f"{settings.basic_auth_users_file}: expected a flat 'user: pass' map"
        )
    return users


# Register additional auth modules here (name -> factory).
AUTH_MODULES = {
    "basic": lambda settings: BasicAuth(_load_basic_auth_users(settings)),
}


def build_auth(settings: Settings):
    if settings.auth_module not in AUTH_MODULES:
        raise ValueError(f"unknown auth module '{settings.auth_module}'")
    return AUTH_MODULES[settings.auth_module](settings)
