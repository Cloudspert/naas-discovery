"""Shared FastAPI dependencies -- same pattern as naas-api's app/api/deps.py."""

from fastapi import HTTPException, Request

from app.auth import AuthError


def get_registry(request: Request):
    return request.app.state.registry


def get_health_cache(request: Request):
    return request.app.state.health_cache


def get_telemetry(request: Request):
    return request.app.state.telemetry


def get_settings_dep(request: Request):
    return request.app.state.settings


def require_auth(request: Request):
    try:
        return request.app.state.auth.authenticate(request)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=exc.message, headers=exc.headers)
