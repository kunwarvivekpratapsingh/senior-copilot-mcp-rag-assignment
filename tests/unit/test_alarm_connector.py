"""Alarm API connector tests — T-CONN-01, T-CONN-02.

Covers FR-24 (timeout and retry) and FR-28 (no secret exposure).

Retry policy is the subtle part and gets the most coverage: retrying the wrong class
of failure is worse than not retrying at all, because it burns the caller's deadline
to arrive at the same answer.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from alarm_api import (
    AlarmApiAuthError,
    AlarmApiClient,
    AlarmApiError,
    AlarmApiInvalidInput,
    AlarmApiNotFound,
    AlarmApiTimeout,
    AlarmApiUpstreamError,
)

BASE_URL = "http://alarm-test:8000"
TOKEN = "unit-test-token"  # noqa: S105 — fake credential for assertions


def make_client(**kwargs: object) -> AlarmApiClient:
    defaults: dict[str, object] = {
        "base_url": BASE_URL,
        "token": TOKEN,
        "max_retries": 2,
        "backoff_base_seconds": 0.0,  # keep the suite fast
    }
    return AlarmApiClient(**{**defaults, **kwargs})  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Request construction
# --------------------------------------------------------------------------- #


class TestRequestConstruction:
    @respx.mock
    async def test_bearer_token_is_injected(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        async with make_client() as client:
            await client.health()
        assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"

    @respx.mock
    async def test_trace_headers_are_injected(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        async with make_client(client_id="test-client") as client:
            await client._request("GET", "/health", trace_id="trace-abc", metadata_tag="tag-1")
        headers = route.calls.last.request.headers
        assert headers["trace_id"] == "trace-abc"
        assert headers["x-client-id"] == "test-client"
        assert headers["x-metadata-tag"] == "tag-1"

    @respx.mock
    async def test_trace_id_is_generated_when_not_supplied(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        async with make_client() as client:
            await client.health()
        assert route.calls.last.request.headers["trace_id"].startswith("trace-")

    @respx.mock
    async def test_none_valued_params_are_dropped(self) -> None:
        """Callers pass optional filters unconditionally; httpx rejects None."""
        route = respx.get(f"{BASE_URL}/assets/search").mock(
            return_value=httpx.Response(200, json={"query": "x", "count": 0, "results": []})
        )
        async with make_client() as client:
            await client.search_assets("pump", limit=5, unit=None)
        url = str(route.calls.last.request.url)
        assert "unit=" not in url
        assert "limit=5" in url

    @respx.mock
    async def test_pagination_parameters_are_passed_through(self) -> None:
        route = respx.get(f"{BASE_URL}/alarms").mock(
            return_value=httpx.Response(
                200,
                json={"data": [], "page": 2, "page_size": 25, "total_count": 0,
                      "has_next": False},
            )
        )
        async with make_client() as client:
            await client.get_alarms(asset_id="AST-0001", page=2, page_size=25)
        url = str(route.calls.last.request.url)
        assert "page=2" in url
        assert "page_size=25" in url


# --------------------------------------------------------------------------- #
# Retry policy — FR-24
# --------------------------------------------------------------------------- #


class TestRetryPolicy:
    @respx.mock
    async def test_retries_on_500_then_succeeds(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            side_effect=[
                httpx.Response(500, json={"error": {"code": "INTERNAL_ERROR", "message": "boom"}}),
                httpx.Response(200, json={"status": "ok"}),
            ]
        )
        async with make_client() as client:
            assert await client.health() == {"status": "ok"}
        assert route.call_count == 2

    @respx.mock
    async def test_gives_up_after_max_retries(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(503, json={"error": {"code": "X", "message": "down"}})
        )
        async with make_client(max_retries=2) as client:
            with pytest.raises(AlarmApiUpstreamError):
                await client.health()
        assert route.call_count == 3  # one initial attempt plus two retries

    @respx.mock
    async def test_does_not_retry_a_400(self) -> None:
        """The same arguments will fail identically; retrying only wastes the deadline."""
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(
                400, json={"error": {"code": "INVALID_INPUT", "message": "bad"}}
            )
        )
        async with make_client() as client:
            with pytest.raises(AlarmApiInvalidInput):
                await client.health()
        assert route.call_count == 1

    @respx.mock
    async def test_does_not_retry_a_401(self) -> None:
        """Retrying turns a clear configuration error into a slow one."""
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(
                401, json={"error": {"code": "AUTH_FAILED", "message": "nope"}}
            )
        )
        async with make_client() as client:
            with pytest.raises(AlarmApiAuthError):
                await client.health()
        assert route.call_count == 1

    @respx.mock
    async def test_does_not_retry_a_404(self) -> None:
        route = respx.get(f"{BASE_URL}/alarms/ALM-1").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NOT_FOUND", "message": "gone"}}
            )
        )
        async with make_client() as client:
            with pytest.raises(AlarmApiNotFound):
                await client.get_alarm("ALM-1")
        assert route.call_count == 1

    @respx.mock
    async def test_retries_connection_errors(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            side_effect=[
                httpx.ConnectError("refused"),
                httpx.Response(200, json={"status": "ok"}),
            ]
        )
        async with make_client() as client:
            assert await client.health() == {"status": "ok"}
        assert route.call_count == 2

    @respx.mock
    async def test_timeout_surfaces_as_alarm_api_timeout(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(side_effect=httpx.ReadTimeout("slow"))
        async with make_client(max_retries=1) as client:
            with pytest.raises(AlarmApiTimeout):
                await client.health()


# --------------------------------------------------------------------------- #
# Error translation
# --------------------------------------------------------------------------- #


class TestErrorTranslation:
    @pytest.mark.parametrize(
        ("status", "expected", "code"),
        [
            (401, AlarmApiAuthError, "AUTH_FAILED"),
            (404, AlarmApiNotFound, "NOT_FOUND"),
            (400, AlarmApiInvalidInput, "INVALID_INPUT"),
            (422, AlarmApiInvalidInput, "INVALID_INPUT"),
            (500, AlarmApiUpstreamError, "UPSTREAM_5XX"),
        ],
    )
    @respx.mock
    async def test_status_maps_to_typed_exception(
        self, status: int, expected: type[AlarmApiError], code: str
    ) -> None:
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(
                status, json={"error": {"code": code, "message": "failed"}}
            )
        )
        async with make_client(max_retries=0) as client:
            with pytest.raises(expected) as caught:
                await client.health()
        assert caught.value.error_code == code

    @respx.mock
    async def test_trace_id_is_carried_onto_the_exception(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(
                404,
                json={"error": {"code": "NOT_FOUND", "message": "gone",
                                "trace_id": "trace-xyz"}},
            )
        )
        async with make_client() as client:
            with pytest.raises(AlarmApiNotFound) as caught:
                await client.health()
        assert caught.value.trace_id == "trace-xyz"

    @respx.mock
    async def test_non_json_error_body_does_not_crash_the_client(self) -> None:
        """A proxy or a crash can return HTML; translation must stay defensive."""
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(502, text="<html>Bad Gateway</html>")
        )
        async with make_client(max_retries=0) as client:
            with pytest.raises(AlarmApiUpstreamError) as caught:
                await client.health()
        assert "Bad Gateway" in caught.value.message


# --------------------------------------------------------------------------- #
# Secret handling — FR-28
# --------------------------------------------------------------------------- #


class TestSecretHandling:
    @respx.mock
    async def test_token_never_appears_in_an_exception(self) -> None:
        """An exception is the most likely thing to be logged or shown to a user."""
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(
                401, json={"error": {"code": "AUTH_FAILED", "message": "rejected"}}
            )
        )
        async with make_client() as client:
            with pytest.raises(AlarmApiAuthError) as caught:
                await client.health()
        assert TOKEN not in str(caught.value)
        assert TOKEN not in repr(caught.value)

    async def test_token_is_not_a_public_attribute(self) -> None:
        client = make_client()
        public = [a for a in dir(client) if not a.startswith("_")]
        assert not any("token" in a.lower() for a in public)
        await client.aclose()
