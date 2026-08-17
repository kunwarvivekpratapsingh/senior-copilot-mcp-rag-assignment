"""HTTP connector for the Alarm Management API.

Reusable client layer, deliberately independent of the MCP server that consumes it.
It knows how to reach the source system; the MCP server knows what the capabilities
mean.
"""

from .client import RETRYABLE_STATUS, AlarmApiClient
from .errors import (
    AlarmApiAuthError,
    AlarmApiError,
    AlarmApiInvalidInput,
    AlarmApiNotFound,
    AlarmApiTimeout,
    AlarmApiUpstreamError,
)

__all__ = [
    "RETRYABLE_STATUS",
    "AlarmApiAuthError",
    "AlarmApiClient",
    "AlarmApiError",
    "AlarmApiInvalidInput",
    "AlarmApiNotFound",
    "AlarmApiTimeout",
    "AlarmApiUpstreamError",
]
