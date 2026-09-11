"""Shared error types, translated to HTTP responses in app/api/deps.py."""


class ApiError(Exception):
    """A domain error that should become an HTTP error response."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConfigError(Exception):
    """Raised when a config file (registry, telemetry, auth users) is invalid.

    Meant to be raised during startup so the app fails fast instead of
    serving a partially-broken registry (see design doc §15).
    """
