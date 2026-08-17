"""Error envelope and exception handlers.

Every non-2xx response carries the same shape::

    {"error": {"code": "NOT_FOUND", "message": "...", "trace_id": "..."}}

A single predictable shape is what lets the MCP server map source-system failures
onto stable ``error_code`` values the orchestrator can branch on, rather than
string-matching prose.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .trace import current_trace_id


class ApiError(Exception):
    """Base for errors that map onto the documented envelope."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ApiError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class InvalidInputError(ApiError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_INPUT"


class AuthError(ApiError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTH_FAILED"


def error_body(code: str, message: str, trace_id: str | None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "trace_id": trace_id}}


def register_error_handlers(app: FastAPI) -> None:
    """Attach handlers so every failure path produces the documented envelope."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, current_trace_id()),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's error list is useful to a developer but noisy to a caller, so
        # summarise it into one message while keeping the field paths.
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'][1:])}: {err['msg']}" for err in exc.errors()
        )
        return JSONResponse(
            # Starlette renamed this constant; use the literal so the code works on
            # both spellings without a version check.
            status_code=422,
            content=error_body("INVALID_INPUT", details or "Request validation failed",
                               current_trace_id()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_401_UNAUTHORIZED: "AUTH_FAILED",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_400_BAD_REQUEST: "INVALID_INPUT",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, str(exc.detail), current_trace_id()),
            headers=getattr(exc, "headers", None),
        )
