"""Trace-header propagation.

The Postman collections send ``trace_id``, ``x-client-id`` and ``x-metadata-tag``
on several requests. The simulator accepts them on every endpoint, generates a
``trace_id`` when the caller does not supply one, and echoes all three back on the
response.

That echo is what lets the MCP server prove end-to-end correlation: the id the
orchestrator generated appears in the source system's response, and from there in
the GUI's execution trace.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

TRACE_HEADER = "trace_id"
CLIENT_HEADER = "x-client-id"
METADATA_HEADER = "x-metadata-tag"

# A context variable rather than a parameter, so error handlers deep in the stack
# can stamp the trace id without every function signature carrying it.
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_client_id: ContextVar[str | None] = ContextVar("client_id", default=None)
_metadata_tag: ContextVar[str | None] = ContextVar("metadata_tag", default=None)


def current_trace_id() -> str | None:
    return _trace_id.get()


def current_client_id() -> str | None:
    return _client_id.get()


def current_metadata_tag() -> str | None:
    return _metadata_tag.get()


def trace_context() -> dict[str, str | None]:
    """The trace triple, for embedding in a response envelope."""
    return {
        "trace_id": _trace_id.get(),
        "client_id": _client_id.get(),
        "metadata_tag": _metadata_tag.get(),
    }


class TraceMiddleware(BaseHTTPMiddleware):
    """Bind incoming trace headers to the request context and echo them back."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get(TRACE_HEADER) or f"trace-{uuid.uuid4().hex[:12]}"
        client_id = request.headers.get(CLIENT_HEADER)
        metadata_tag = request.headers.get(METADATA_HEADER)

        trace_token = _trace_id.set(trace_id)
        client_token = _client_id.set(client_id)
        metadata_token = _metadata_tag.set(metadata_tag)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            if client_id:
                response.headers[CLIENT_HEADER] = client_id
            if metadata_tag:
                response.headers[METADATA_HEADER] = metadata_tag
            return response
        finally:
            _trace_id.reset(trace_token)
            _client_id.reset(client_token)
            _metadata_tag.reset(metadata_token)
