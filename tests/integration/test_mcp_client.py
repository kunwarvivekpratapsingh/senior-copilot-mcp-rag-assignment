"""MCP client tests — T-MCPC-01..04.

Covers FR-03 (discovery), FR-04 (schema-aware invocation), FR-05 (chaining),
FR-06 (cross-server), FR-18 (invalid arguments), FR-19 (unavailable tools/servers),
FR-20 (partial failure), FR-30 (write approval).

Exercised against the **real** MCP servers, connected in-process. The client, the
protocol, both servers, and the simulator all run genuinely; only the socket is
elided.

Each test opens the registry with ``async with``. The MCP ``Client`` holds an anyio
task group that must be entered and exited from the same task, and pytest runs
fixture teardown in a different task than setup — so a yielding fixture cannot hold
these sessions. Scoping them to the test body makes the constraint structural.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from alarm_api import AlarmApiClient
from alarm_mcp.server import mcp as alarm_server
from alarm_mcp.server import set_client
from alarm_simulator.main import app as simulator_app
from copilot_backend.mcp_client import (
    InvalidToolArgumentsError,
    McpServerConfig,
    ToolInvoker,
    ToolNotFoundError,
    ToolRegistry,
)
from github_mcp.server import mcp as github_server


@asynccontextmanager
async def connected() -> AsyncIterator[tuple[ToolRegistry, ToolInvoker]]:
    """A registry connected to both MCP servers, plus an invoker over it."""
    set_client(
        AlarmApiClient(
            base_url="http://alarm-simulator",
            token="demo-token",  # noqa: S106
            transport=httpx.ASGITransport(app=simulator_app),
            max_retries=0,
        )
    )
    servers = [
        McpServerConfig("alarm-management", alarm_server),
        McpServerConfig("github-issues", github_server),
    ]
    try:
        async with ToolRegistry(servers=servers) as registry:
            yield registry, ToolInvoker(registry=registry)
    finally:
        set_client(None)


def window() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "start_time": (now - timedelta(days=90)).isoformat(),
        "end_time": now.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Discovery — FR-03
# --------------------------------------------------------------------------- #


class TestDiscovery:
    async def test_discovers_tools_from_both_servers(self, sim_client: object) -> None:
        async with connected() as (registry, _):
            assert registry.tool_count == 17  # 14 alarm + 3 github

    async def test_reports_per_server_status(self, sim_client: object) -> None:
        async with connected() as (registry, _):
            statuses = {s.name: s for s in registry.server_status()}
            assert statuses["alarm-management"].connected
            assert statuses["alarm-management"].tool_count == 14
            assert statuses["github-issues"].connected
            assert statuses["github-issues"].tool_count == 3

    async def test_specs_carry_the_owning_server(self, sim_client: object) -> None:
        """The GUI shows which server handled a step; the spec is where that comes from."""
        async with connected() as (registry, _):
            assert registry.get("search_assets").server == "alarm-management"
            assert registry.get("draft_issue").server == "github-issues"
            assert (
                registry.get("search_assets").qualified_name
                == "alarm-management/search_assets"
            )

    async def test_planner_catalogue_is_stable_between_calls(
        self, sim_client: object
    ) -> None:
        """An unstable ordering would invalidate the prompt cache on every request."""
        async with connected() as (registry, _):
            assert registry.catalogue_for_planner() == registry.catalogue_for_planner()

    async def test_planner_catalogue_omits_output_schemas(self, sim_client: object) -> None:
        """The planner picks tools and arguments; response shapes only spend context."""
        async with connected() as (registry, _):
            for entry in registry.catalogue_for_planner():
                assert set(entry) == {"server", "name", "description", "input_schema"}

    async def test_an_unavailable_server_is_degraded_not_fatal(
        self, sim_client: object
    ) -> None:
        """One server being down must not take the whole copilot with it."""
        servers = [
            McpServerConfig("github-issues", github_server),
            McpServerConfig("nonexistent", "http://127.0.0.1:1/mcp"),
        ]
        async with ToolRegistry(servers=servers) as registry:
            statuses = {s.name: s for s in registry.server_status()}
            assert statuses["github-issues"].connected
            assert not statuses["nonexistent"].connected
            assert statuses["nonexistent"].error
            # The working server's tools remain usable.
            assert registry.tool_count == 3


# --------------------------------------------------------------------------- #
# Invocation and chaining — FR-04, FR-05, FR-06
# --------------------------------------------------------------------------- #


class TestInvocation:
    async def test_successful_invocation_returns_a_uniform_result(
        self, sim_client: object
    ) -> None:
        async with connected() as (_, invoker):
            result = await invoker.invoke("search_assets", {"query": "Boiler Feed Pump 101"})
            assert result.ok
            assert result.server == "alarm-management"
            assert result.tool == "search_assets"
            assert result.duration_ms > 0
            assert result.error_code is None
            assert (result.output or {})["count"] >= 1

    async def test_output_of_one_tool_feeds_the_next(self, sim_client: object) -> None:
        """This is what 'multi-step tool chaining' means."""
        async with connected() as (_, invoker):
            first = await invoker.invoke("search_assets", {"query": "Boiler Feed Pump 101"})
            asset_id = (first.output or {})["results"][0]["asset_id"]

            second = await invoker.invoke(
                "get_alarm_summary",
                {
                    "asset_ids": [asset_id],  # the value the previous step produced
                    **window(),
                    "severity": ["high", "critical"],
                },
            )
            assert second.ok
            assert (second.output or {})["total_alarms"] > 0

    async def test_a_chain_can_span_two_servers(self, sim_client: object) -> None:
        """FR-06: a plan is not confined to one MCP server."""
        async with connected() as (_, invoker):
            assets = await invoker.invoke("search_assets", {"query": "Boiler Feed Pump 101"})
            asset_name = (assets.output or {})["results"][0]["asset_name"]

            issues = await invoker.invoke("search_issues", {"query": asset_name})
            assert issues.ok
            assert assets.server == "alarm-management"
            assert issues.server == "github-issues"

    async def test_trace_id_is_propagated_into_the_tool(self, sim_client: object) -> None:
        async with connected() as (_, invoker):
            result = await invoker.invoke(
                "search_assets", {"query": "pump"}, trace_id="trace-client-test"
            )
            assert result.trace_id == "trace-client-test"

    async def test_trace_id_is_not_injected_into_tools_that_reject_it(
        self, sim_client: object
    ) -> None:
        """search_issues has no trace_id parameter; injecting it would fail validation."""
        async with connected() as (_, invoker):
            result = await invoker.invoke(
                "search_issues", {"query": "pump"}, trace_id="trace-client-test"
            )
            assert result.ok


# --------------------------------------------------------------------------- #
# Failure modes — FR-18, FR-19, FR-20
# --------------------------------------------------------------------------- #


class TestFailureModes:
    async def test_invalid_arguments_are_rejected_before_the_network(
        self, sim_client: object
    ) -> None:
        """Sending arguments we already know are invalid spends a round trip to learn
        what the schema already told us."""
        async with connected() as (_, invoker):
            result = await invoker.invoke("search_assets", {"limit": 5})  # 'query' required
            assert not result.ok
            assert result.error_code == "INVALID_INPUT"
            # Rejected locally, so far faster than any real call could return.
            assert result.duration_ms < 20

    async def test_validation_reports_every_violation_not_just_the_first(
        self, sim_client: object
    ) -> None:
        """A caller should fix one plan, not iterate one field at a time."""
        async with connected() as (_, invoker):
            with pytest.raises(InvalidToolArgumentsError) as caught:
                invoker.validate("search_assets", {"limit": 999})
            assert len(caught.value.violations) >= 2

    async def test_wrong_argument_type_is_rejected(self, sim_client: object) -> None:
        async with connected() as (_, invoker):
            result = await invoker.invoke("search_assets", {"query": "pump", "limit": "many"})
            assert not result.ok
            assert result.error_code == "INVALID_INPUT"

    async def test_unknown_tool_is_rejected_without_a_call(self, sim_client: object) -> None:
        async with connected() as (_, invoker):
            result = await invoker.invoke("no_such_tool", {})
            assert not result.ok
            assert result.error_code == "TOOL_NOT_FOUND"

    async def test_unknown_tool_error_lists_what_is_available(
        self, sim_client: object
    ) -> None:
        """The usual cause is a plan naming a tool that does not exist."""
        async with connected() as (registry, _):
            with pytest.raises(ToolNotFoundError) as caught:
                registry.get("get_alarm_summry")  # typo
            assert "search_assets" in str(caught.value)

    async def test_a_tool_failure_is_reported_as_a_failure(
        self, sim_client: object
    ) -> None:
        """The client returns an errored result rather than raising, so treating
        'no exception' as success would silently report failed steps as successful."""
        async with connected() as (_, invoker):
            result = await invoker.invoke("get_alarm_by_id", {"alarm_id": "ALM-99999"})
            assert not result.ok
            assert result.error_code == "NOT_FOUND"
            assert result.output is None

    async def test_failure_returns_a_result_rather_than_raising(
        self, sim_client: object
    ) -> None:
        """One envelope for success and failure lets the timeline and the logs consume
        the same object."""
        async with connected() as (_, invoker):
            result = await invoker.invoke("get_alarm_by_id", {"alarm_id": "ALM-99999"})
            assert result.tool == "get_alarm_by_id"
            assert result.arguments == {"alarm_id": "ALM-99999"}
            assert "NOT_FOUND" in result.summary()

    async def test_partial_failure_leaves_later_steps_runnable(
        self, sim_client: object
    ) -> None:
        """FR-20: one bad step must not poison the rest of the chain."""
        async with connected() as (_, invoker):
            failed = await invoker.invoke("get_alarm_by_id", {"alarm_id": "ALM-99999"})
            recovered = await invoker.invoke("search_assets", {"query": "pump"})
            assert not failed.ok
            assert recovered.ok


# --------------------------------------------------------------------------- #
# Write approval — FR-30
# --------------------------------------------------------------------------- #


class TestWriteApproval:
    async def test_draft_issue_writes_nothing(self, sim_client: object) -> None:
        async with connected() as (_, invoker):
            result = await invoker.invoke(
                "draft_issue",
                {
                    "title": "Recurring alarms on BFP-101",
                    "summary": "39 occurrences in 90 days.",
                },
            )
            assert result.ok
            assert (result.output or {})["is_draft"] is True
            assert (result.output or {})["confirmation_required"] is True

    async def test_create_issue_refuses_without_confirmation(
        self, sim_client: object
    ) -> None:
        """The gate is in the tool contract, so it holds for every caller — including
        the model, and including anything that bypasses the UI."""
        async with connected() as (_, invoker):
            result = await invoker.invoke("create_issue", {"title": "T", "body": "B"})
            assert not result.ok
            # The code is extracted into its own field and stripped from the message,
            # so the orchestrator branches on the code and shows the prose to the user.
            assert result.error_code == "CONFIRMATION_REQUIRED"
            assert "requires explicit human confirmation" in (result.error_message or "")

    async def test_create_issue_succeeds_once_confirmed(self, sim_client: object) -> None:
        async with connected() as (_, invoker):
            result = await invoker.invoke(
                "create_issue",
                {"title": "Recurring alarms on BFP-101", "body": "Details.",
                 "confirmed": True},
            )
            assert result.ok
            assert (result.output or {})["created"] is True
            assert (result.output or {})["number"] > 0
