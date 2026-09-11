"""Auth primitives shared by all modules.

Vendored from naas-api's app/auth/base.py (§10), unchanged except the
realm string below -- "naas-api" would be actively wrong here, it's a
different service. See docs/DEV_LOG.md.
"""

from dataclasses import dataclass

BASIC_CHALLENGE = {"WWW-Authenticate": 'Basic realm="naas-discovery"'}


@dataclass
class Principal:
    username: str
    module: str


class AuthError(Exception):
    def __init__(self, message, headers=None):
        super().__init__(message)
        self.message = message
        self.headers = headers or {}
