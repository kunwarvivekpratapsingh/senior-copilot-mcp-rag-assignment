"""Observability.

One model emits the fields the submission guidelines grade on, and the **same**
object populates the execution-timeline API the GUI renders. Observability and GUI
traceability are therefore one feature rather than two that can drift apart.

Graded fields: ``request_id``, ``conversation_id``, ``trace_id``, ``mcp_server``,
``mcp_tool``, ``duration_ms``, ``outcome``, ``api_status_code``, ``retry_count``,
``retrieval_query``, ``retrieved_doc_ids``, ``retrieval_score``, ``llm_latency_ms``.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

REDACTED = "***redacted***"

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(sk-ant-)[A-Za-z0-9._\-]+"),
    re.compile(r"(ghp_)[A-Za-z0-9]+"),
]
_SENSITIVE_KEYS = {"token", "api_key", "apikey", "authorization", "password", "secret"}

# Request-scoped identifiers, so every log line inside a request is correlated
# without threading three arguments through every function signature.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_conversation_id: ContextVar[str | None] = ContextVar("conversation_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_request_context(conversation_id: str | None = None) -> tuple[str, str, str]:
    """Start a request context, returning ``(request_id, conversation_id, trace_id)``."""
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    conversation = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    _request_id.set(request_id)
    _conversation_id.set(conversation)
    _trace_id.set(trace_id)
    return request_id, conversation, trace_id


def current_context() -> dict[str, str | None]:
    return {
        "request_id": _request_id.get(),
        "conversation_id": _conversation_id.get(),
        "trace_id": _trace_id.get(),
    }


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub(rf"\1{REDACTED}", value)
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if k.lower() in _SENSITIVE_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def redact_processor(_l: Any, _m: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Scrub secrets from every field of every record.

    A processor rather than a call-site convention, because "remember not to log the
    token" is a hope, not a control.
    """
    return {key: _scrub(value) for key, value in event_dict.items()}


def context_processor(_l: Any, _m: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Attach the request-scoped identifiers to every record."""
    for key, value in current_context().items():
        if value is not None:
            event_dict.setdefault(key, value)
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), 20)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            context_processor,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.JSONRenderer()
            if json_output
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), 20)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "copilot") -> Any:
    return structlog.get_logger(name)
