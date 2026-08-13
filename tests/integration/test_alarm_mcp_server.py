"""Alarm Management MCP server tests — T-MCPS-01..04.

Covers FR-03 (tool discovery), FR-04 (schema validation), FR-23 (auth handling),
FR-25 (error mapping), FR-26 (trace propagation), FR-29 (independently testable).

The server is exercised against the **real simulator**, wired in-process with an ASGI
transport rather than over a socket. That keeps the test fast and hermetic while still
running the genuine HTTP path — request construction, auth header, trace headers, and
response parsing all execute exactly as they would in production.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from alarm_api import AlarmApiClient
from alarm_mcp import parse_error_code
from alarm_mcp.server import get_client, mcp, set_client
from alarm_simulator.main import app as simulator_app
from fastapi.testclient import TestClient

# The SDK wraps any exception a tool raises in its own ToolError. Our machine-readable
# "[CODE] message" prefix survives that wrapping, which is exactly why the contract is
# carried in the message rather than in an exception type the SDK would discard.
from mcp.server.mcpserver.exceptions import ToolError as SdkToolError

TOKEN = "demo-token"  # noqa: S105 — the simulator's documented default


def raised_code(exc: BaseException) -> str:
    """Recover the stable error code from whatever the SDK surfaced."""
    return parse_error_code(str(exc).split("Error executing tool ", 1)[-1].split(": ", 1)[-1])[0]


@pytest.fixture(scope="module")
def mcp_client(sim_client: TestClient) -> Iterator[AlarmApiClient]:
    """Point the MCP server's connector at the in-process simulator.

    Depends on ``sim_client`` so the simulator's lifespan has run and the database is
    seeded before any tool executes.
    """
    client = AlarmApiClient(
        base_url="http://alarm-simulator",
        token=TOKEN,
        transport=httpx.ASGITransport(app=simulator_app),
        max_retries=0,
    )
    set_client(client)
    yield client
    set_client(None)


@pytest.fixture(scope="module")
def window() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "start_time": (now - timedelta(days=90)).isoformat(),
        "end_time": now.isoformat(),
    }


async def call(name: str, **kwargs: object) -> object:
    """Invoke a tool the way an MCP client would — by name, with a dict of arguments."""
    return await mcp.call_tool(name, kwargs)


# --------------------------------------------------------------------------- #
# Discovery — FR-03
# --------------------------------------------------------------------------- #


class TestToolDiscovery:
    async def test_all_fourteen_tools_are_registered(self) -> None:
        tools = await mcp.list_tools()
        assert len(tools) == 14

    async def test_every_tool_has_a_description_written_for_a_model(self) -> None:
        """A vague description produces a wrong plan no validation can repair."""
        for tool in await mcp.list_tools():
            assert tool.description, f"{tool.name} has no description"
            assert len(tool.description) > 80, f"{tool.name}'s description is too thin"

    async def test_every_tool_publishes_input_and_output_schemas(self) -> None:
        for tool in await mcp.list_tools():
            assert tool.input_schema, f"{tool.name} has no input schema"
            assert tool.output_schema, f"{tool.name} has no output schema"

    async def test_no_tool_accepts_a_credential(self) -> None:
        """The security boundary: there is no path from the model to the token."""
        offenders = [
            (tool.name, param)
            for tool in await mcp.list_tools()
            for param in (tool.input_schema or {}).get("properties", {})
            if any(s in param.lower() for s in ("token", "secret", "password", "api_key"))
        ]
        assert offenders == []


# --------------------------------------------------------------------------- #
# Invocation
# --------------------------------------------------------------------------- #


class TestToolInvocation:
    async def test_search_assets_resolves_a_name_to_an_id(
        self, mcp_client: AlarmApiClient
    ) -> None:
        result = await call("search_assets", query="Boiler Feed Pump 101", limit=5)
        payload = _structured(result)
        assert payload["count"] >= 1
        assert payload["results"][0]["asset_name"] == "Boiler Feed Pump 101"
        assert payload["results"][0]["asset_id"].startswith("AST-")

    async def test_get_alarms_paginates(self, mcp_client: AlarmApiClient) -> None:
        assets = _structured(await call("search_assets", query="Boiler Feed Pump 101"))
        asset_id = assets["results"][0]["asset_id"]
        payload = _structured(await call("get_alarms", asset_id=asset_id, page_size=5))
        assert len(payload["data"]) == 5
        assert payload["total_count"] > 5
        assert payload["has_next"] is True

    async def test_correlation_returns_the_engineered_pair(
        self, mcp_client: AlarmApiClient, window: dict[str, str]
    ) -> None:
        """The acceptance scenario depends on this returning a real finding."""
        assets = _structured(await call("search_assets", query="Boiler Feed Pump 101"))
        asset_id = assets["results"][0]["asset_id"]
        payload = _structured(
            await call(
                "get_alarm_correlation",
                asset_ids=[asset_id],
                start_time=window["start_time"],
                end_time=window["end_time"],
                min_support=5,
            )
        )
        assert payload["pairs"], "correlation must find the seeded co-occurring pair"
        top = payload["pairs"][0]
        assert top["support"] >= 5
        # Lift above 1.0 is what distinguishes a real association from coincidence.
        assert top["lift"] > 1.0

    async def test_calculation_generate_then_execute_chains(
        self, mcp_client: AlarmApiClient
    ) -> None:
        """The second tool is impossible without the first — a genuine chain."""
        generated = _structured(
            await call(
                "generate_calculation",
                calculation_type="operator_response_efficiency",
                site="SouthPlant",
            )
        )
        assert generated["calculation_id"].startswith("CALC-")

        executed = _structured(
            await call("execute_calculation", calculation_id=generated["calculation_id"])
        )
        assert executed["calculation_id"] == generated["calculation_id"]
        assert 0.0 <= executed["value"] <= 1.0
        assert executed["interpretation"]

    async def test_priority_score_returns_an_explained_breakdown(
        self, mcp_client: AlarmApiClient
    ) -> None:
        assets = _structured(await call("search_assets", query="Boiler Feed Pump 101"))
        alarms = _structured(
            await call("get_alarms", asset_id=assets["results"][0]["asset_id"], page_size=1)
        )
        payload = _structured(
            await call("get_priority_score", alarm_id=alarms["data"][0]["alarm_id"])
        )
        assert 0.0 <= payload["priority_score"] <= 100.0
        assert len(payload["factors"]) == 4
        assert all(f["explanation"] for f in payload["factors"])


# --------------------------------------------------------------------------- #
# Trace propagation — FR-26
# --------------------------------------------------------------------------- #


class TestTracePropagation:
    async def test_supplied_trace_id_is_returned_in_tool_metadata(
        self, mcp_client: AlarmApiClient
    ) -> None:
        payload = _structured(
            await call("search_assets", query="pump", trace_id="trace-mcp-test-1")
        )
        assert payload["meta"]["trace_id"] == "trace-mcp-test-1"

    async def test_trace_id_is_generated_when_the_caller_omits_it(
        self, mcp_client: AlarmApiClient
    ) -> None:
        payload = _structured(await call("search_assets", query="pump"))
        assert payload["meta"]["trace_id"].startswith("trace-")


# --------------------------------------------------------------------------- #
# Error mapping — FR-25
# --------------------------------------------------------------------------- #


class TestErrorMapping:
    async def test_unknown_alarm_maps_to_not_found(self, mcp_client: AlarmApiClient) -> None:
        with pytest.raises(SdkToolError) as caught:
            await call("get_alarm_by_id", alarm_id="ALM-99999")
        assert raised_code(caught.value) == "NOT_FOUND"

    async def test_error_code_is_recoverable_from_the_message(
        self, mcp_client: AlarmApiClient
    ) -> None:
        """The prefix is the contract the orchestrator branches on.

        It is carried in the message specifically because the SDK wraps the raised
        exception in its own type, discarding any custom attributes.
        """
        with pytest.raises(SdkToolError) as caught:
            await call("get_priority_score", alarm_id="ALM-99999")
        assert "[NOT_FOUND]" in str(caught.value)
        assert raised_code(caught.value) == "NOT_FOUND"

    async def test_auth_failure_maps_to_auth_failed(
        self, mcp_client: AlarmApiClient
    ) -> None:
        """A wrong token must be reported as configuration, not as a missing record."""
        original = get_client()
        bad = AlarmApiClient(
            base_url="http://alarm-simulator",
            token="wrong-token",  # noqa: S106
            transport=httpx.ASGITransport(app=simulator_app),
            max_retries=0,
        )
        set_client(bad)
        try:
            with pytest.raises(SdkToolError) as caught:
                await call("search_assets", query="pump")
            assert raised_code(caught.value) == "AUTH_FAILED"
        finally:
            # Restore the module fixture's client, not None: setting None makes the
            # next tool call lazily build one from settings and time out.
            set_client(original)
            await bad.aclose()

    async def test_unreachable_upstream_maps_to_timeout(
        self, mcp_client: AlarmApiClient
    ) -> None:
        original = get_client()
        unreachable = AlarmApiClient(
            base_url="http://127.0.0.1:1",  # nothing listens on port 1
            token=TOKEN,
            timeout_seconds=0.5,
            max_retries=0,
            backoff_base_seconds=0.0,
        )
        set_client(unreachable)
        try:
            with pytest.raises(SdkToolError) as caught:
                await call("search_assets", query="pump")
            assert raised_code(caught.value) == "TIMEOUT"
        finally:
            set_client(original)
            await unreachable.aclose()

    async def test_parse_error_code_classifies_an_unprefixed_message(self) -> None:
        code, message = parse_error_code("something unexpected happened")
        assert code == "INTERNAL_ERROR"
        assert message == "something unexpected happened"


# --------------------------------------------------------------------------- #
# Schema validation — FR-04
# --------------------------------------------------------------------------- #


class TestSchemaValidation:
    async def test_missing_required_argument_is_rejected(
        self, mcp_client: AlarmApiClient
    ) -> None:
        with pytest.raises(Exception) as caught:  # noqa: B017 — SDK-specific type
            await mcp.call_tool("get_priority_score", {})
        assert "alarm_id" in str(caught.value).lower()

    async def test_unknown_tool_is_rejected(self, mcp_client: AlarmApiClient) -> None:
        with pytest.raises(Exception) as caught:  # noqa: B017 — SDK-specific type
            await mcp.call_tool("no_such_tool", {})
        assert "no_such_tool" in str(caught.value).lower()


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #


def _structured(result: object) -> dict:
    """Extract the structured payload from an MCP tool result.

    ``call_tool`` returns a (content, structured) pair in this SDK version; tolerate
    a bare value too so the tests survive a shape change.
    """
    if isinstance(result, tuple) and len(result) == 2:
        return dict(result[1])
    if isinstance(result, dict):
        return result
    return dict(getattr(result, "structured_content", result))  # type: ignore[arg-type]
