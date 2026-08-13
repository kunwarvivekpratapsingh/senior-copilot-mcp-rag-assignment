"""Bearer-token authentication.

Every endpoint except ``/health`` requires ``Authorization: Bearer <token>``.
``/health`` is deliberately unauthenticated so container health checks and the
Postman collection's first request work without credentials.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Request

from .config import Settings, get_settings
from .errors import AuthError


def require_bearer_token(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    """FastAPI dependency enforcing the bearer token.

    Comparison uses :func:`hmac.compare_digest` rather than ``==`` so the check
    runs in constant time and cannot be probed character by character.
    """
    header = request.headers.get("authorization")
    if not header:
        raise AuthError("Missing Authorization header")

    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Authorization header must use the Bearer scheme")

    if not hmac.compare_digest(token.strip(), settings.alarm_api_token):
        raise AuthError("Invalid bearer token")
