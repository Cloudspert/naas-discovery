import base64

import pytest
from starlette.requests import Request

from app.auth import _load_basic_auth_users, build_auth
from app.auth.base import AuthError
from app.auth.basic import BasicAuth
from app.core.config import Settings


def _request_with_auth_header(header_value: str | None) -> Request:
    headers = [(b"authorization", header_value.encode())] if header_value else []
    scope = {"type": "http", "headers": headers, "method": "GET", "path": "/"}
    return Request(scope)


def _basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def test_authenticate_succeeds_with_correct_credentials():
    auth = BasicAuth({"admin": "changeme"})
    request = _request_with_auth_header(_basic_header("admin", "changeme"))

    principal = auth.authenticate(request)

    assert principal.username == "admin"
    assert principal.module == "basic"


def test_authenticate_rejects_wrong_password():
    auth = BasicAuth({"admin": "changeme"})
    request = _request_with_auth_header(_basic_header("admin", "wrong"))

    with pytest.raises(AuthError):
        auth.authenticate(request)


def test_authenticate_rejects_unknown_user():
    auth = BasicAuth({"admin": "changeme"})
    request = _request_with_auth_header(_basic_header("someone-else", "changeme"))

    with pytest.raises(AuthError):
        auth.authenticate(request)


def test_authenticate_rejects_missing_header():
    auth = BasicAuth({"admin": "changeme"})
    request = _request_with_auth_header(None)

    with pytest.raises(AuthError):
        auth.authenticate(request)


def test_authenticate_rejects_malformed_base64():
    auth = BasicAuth({"admin": "changeme"})
    request = _request_with_auth_header("Basic not-valid-base64!!!")

    with pytest.raises(AuthError):
        auth.authenticate(request)


def test_build_auth_returns_basic_auth_for_default_settings():
    settings = Settings(basic_auth_users={"admin": "changeme"})

    auth = build_auth(settings)

    assert isinstance(auth, BasicAuth)
    assert auth.users == {"admin": "changeme"}


def test_load_basic_auth_users_from_env_when_no_file_set():
    settings = Settings(basic_auth_users={"admin": "changeme"})

    assert _load_basic_auth_users(settings) == {"admin": "changeme"}


def test_load_basic_auth_users_file_takes_precedence_over_env(tmp_path):
    users_file = tmp_path / "basic-auth-users.yaml"
    users_file.write_text("admin: from-file\n")

    settings = Settings(
        basic_auth_users={"admin": "from-env"}, basic_auth_users_file=str(users_file)
    )

    assert _load_basic_auth_users(settings) == {"admin": "from-file"}
