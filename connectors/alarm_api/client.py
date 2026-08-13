"""Async HTTP client for the Alarm Management API.

Deliberately separate from the MCP server. This module knows how to *reach* the
source system — authentication, trace headers, timeouts, retries, error translation.
The MCP server knows what the capabilities *mean*. Keeping them apart is what makes
this a reusable connector rather than plumbing welded to one consumer.

Two behaviours carry most of the weight:

**The token never leaves this module.** It is read from configuration at construction
and attached to every request. It is never a method parameter, never logged, and never
included in an exception. There is no code path by which a caller — including a
language model driving the MCP server — can read it.

**Retries are restricted to failures that retrying can fix.** 5xx and connection
errors get exponential backoff; 4xx does not. Retrying a 400 wastes the caller's
deadline to arrive at the same answer, and retrying a 401 turns a clear configuration
error into a slow one.
"""

from __future__ import annotations

import asyncio
import uuid
from types import TracebackType
from typing import Any, Self

import httpx

from .errors import (
    AlarmApiAuthError,
    AlarmApiError,
    AlarmApiInvalidInput,
    AlarmApiNotFound,
    AlarmApiTimeout,
    AlarmApiUpstreamError,
)

# Status codes that justify another attempt. Everything else is answered.
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class AlarmApiClient:
    """Typed async client for the Alarm Management API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        client_id: str = "copilot-mcp",
        backoff_base_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token  # never exposed, never logged
        self._client_id = client_id
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- request plumbing --------------------------------------------------- #

    def _headers(self, trace_id: str, metadata_tag: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "trace_id": trace_id,
            "x-client-id": self._client_id,
        }
        if metadata_tag:
            headers["x-metadata-tag"] = metadata_tag
        return headers

    @staticmethod
    def _translate(response: httpx.Response) -> AlarmApiError:
        """Map an error response onto a typed exception.

        The API guarantees one envelope shape, but a proxy or a crash can produce
        something else, so parsing is defensive and falls back to the raw text.
        """
        message = f"HTTP {response.status_code}"
        upstream_code: str | None = None
        trace_id = response.headers.get("trace_id")

        try:
            payload = response.json()
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            upstream_code = error.get("code")
            message = error.get("message", message)
            trace_id = error.get("trace_id") or trace_id
        except ValueError:
            message = response.text[:300] or message

        kwargs: dict[str, Any] = {
            "status_code": response.status_code,
            "trace_id": trace_id,
            "upstream_code": upstream_code,
        }
        if response.status_code == 401:
            return AlarmApiAuthError(message, **kwargs)
        if response.status_code == 404:
            return AlarmApiNotFound(message, **kwargs)
        if response.status_code in (400, 422):
            return AlarmApiInvalidInput(message, **kwargs)
        if response.status_code >= 500:
            return AlarmApiUpstreamError(message, **kwargs)
        return AlarmApiError(message, **kwargs)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        trace_id: str | None = None,
        metadata_tag: str | None = None,
    ) -> dict[str, Any]:
        """Issue one request, retrying only failures a retry can fix."""
        trace_id = trace_id or f"trace-{uuid.uuid4().hex[:12]}"
        headers = self._headers(trace_id, metadata_tag)
        # httpx rejects None values in params; drop them so optional filters can be
        # passed through unconditionally by callers.
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        last_error: AlarmApiError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(
                    method, path, params=clean_params, json=json, headers=headers
                )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                last_error = AlarmApiTimeout(
                    f"{type(exc).__name__} contacting the Alarm Management API",
                    trace_id=trace_id,
                )
            else:
                if response.status_code < 400:
                    result: dict[str, Any] = response.json()
                    return result
                error = self._translate(response)
                if response.status_code not in RETRYABLE_STATUS:
                    raise error
                last_error = error

            if attempt < self._max_retries:
                # Exponential backoff: 0.25s, 0.5s, 1.0s ...
                await asyncio.sleep(self._backoff_base * (2**attempt))

        assert last_error is not None  # noqa: S101 — loop always assigns before exit
        raise last_error

    # -- endpoints ---------------------------------------------------------- #

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def search_assets(
        self, query: str, *, limit: int = 10, unit: str | None = None, **trace: Any
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/assets/search",
            params={"query": query, "limit": limit, "unit": unit}, **trace
        )

    async def get_asset_metadata(self, asset_id: str, **trace: Any) -> dict[str, Any]:
        return await self._request("GET", f"/assets/{asset_id}/metadata", **trace)

    async def get_alarms(
        self,
        *,
        asset_id: str | None = None,
        unit: str | None = None,
        site: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "start_time",
        sort_order: str = "desc",
        **trace: Any,
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/alarms",
            params={
                "asset_id": asset_id, "unit": unit, "site": site, "status": status,
                "severity": severity, "start_time": start_time, "end_time": end_time,
                "page": page, "page_size": page_size,
                "sort_by": sort_by, "sort_order": sort_order,
            },
            **trace,
        )

    async def get_alarm(self, alarm_id: str, **trace: Any) -> dict[str, Any]:
        return await self._request("GET", f"/alarms/{alarm_id}", **trace)

    async def alarm_summary(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request("POST", "/alarms/summary", json=body, **trace)

    async def alarm_trends(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request("POST", "/alarms/trends", json=body, **trace)

    async def alarm_correlation(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request("POST", "/alarms/correlation", json=body, **trace)

    async def flood_analysis(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request("POST", "/alarms/flood-analysis", json=body, **trace)

    async def rationalization_candidates(
        self, body: dict[str, Any], **trace: Any
    ) -> dict[str, Any]:
        return await self._request(
            "POST", "/alarms/rationalization-candidates", json=body, **trace
        )

    async def priority_score(self, alarm_id: str, **trace: Any) -> dict[str, Any]:
        return await self._request(
            "POST", "/alarms/priority-score", json={"alarm_id": alarm_id}, **trace
        )

    async def operator_actions(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request(
            "POST", "/recommendations/operator-actions", json=body, **trace
        )

    async def generate_calculation(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request("POST", "/calculation-code/generate", json=body, **trace)

    async def execute_calculation(self, body: dict[str, Any], **trace: Any) -> dict[str, Any]:
        return await self._request("POST", "/calculation-code/execute", json=body, **trace)

    async def kpi_definitions(self, **trace: Any) -> dict[str, Any]:
        return await self._request("GET", "/analytics/kpi-definitions", **trace)
