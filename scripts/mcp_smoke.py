#!/usr/bin/env python
"""Chain two MCP tools with no GUI and no language model.

This is the moment the architecture becomes real: it proves runtime tool discovery,
schema-validated invocation, and — most importantly — **chaining**, where a value
produced by one tool becomes the input to the next. Everything downstream is built on
this working.

Run against the in-process servers (no containers needed)::

    python scripts/mcp_smoke.py

Or against running MCP servers over HTTP::

    python scripts/mcp_smoke.py --http
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot_backend.mcp_client import McpServerConfig, ToolInvoker, ToolRegistry  # noqa: E402
from copilot_backend.telemetry import configure_logging, new_request_context  # noqa: E402


def build_servers(use_http: bool) -> list[McpServerConfig]:
    if use_http:
        return [
            McpServerConfig("alarm-management", "http://localhost:9000/mcp"),
            McpServerConfig("github-issues", "http://localhost:9001/mcp"),
        ]

    # In-process: point the alarm connector at the simulator's ASGI app so the whole
    # chain runs in one process without a single socket.
    import httpx
    from alarm_api import AlarmApiClient
    from alarm_mcp.server import mcp as alarm_server
    from alarm_mcp.server import set_client
    from alarm_simulator.config import get_settings as sim_settings
    from alarm_simulator.db import init_db
    from alarm_simulator.main import app as simulator_app
    from alarm_simulator.seed import seed_database
    from github_mcp.server import mcp as github_server
    from sqlalchemy.orm import Session

    settings = sim_settings()
    engine = init_db(settings)
    with Session(engine) as session:
        seed_database(session, settings)

    set_client(
        AlarmApiClient(
            base_url="http://alarm-simulator",
            token=settings.alarm_api_token,
            transport=httpx.ASGITransport(app=simulator_app),
            max_retries=0,
        )
    )
    return [
        McpServerConfig("alarm-management", alarm_server),
        McpServerConfig("github-issues", github_server),
    ]


async def main(use_http: bool) -> int:
    configure_logging("WARNING", json_output=False)
    _, _, trace_id = new_request_context()

    registry = ToolRegistry(servers=build_servers(use_http))
    await registry.connect()
    invoker = ToolInvoker(registry=registry)

    try:
        print("\n=== 1. Discovery ===")
        for status in registry.server_status():
            state = "connected" if status.connected else f"UNAVAILABLE ({status.error})"
            print(f"  {status.name:20s} {state}  tools={status.tool_count}")
        print(f"  total tools discovered: {registry.tool_count}")

        print("\n=== 2. Step one: resolve a name to an id ===")
        step1 = await invoker.invoke(
            "search_assets", {"query": "Boiler Feed Pump 101", "limit": 5}, trace_id=trace_id
        )
        if not step1.ok:
            print(f"  FAILED: {step1.error_code} {step1.error_message}")
            return 1
        asset = (step1.output or {})["results"][0]
        asset_id = asset["asset_id"]
        print(f"  {step1.summary()}")
        print(f"  resolved: {asset['asset_name']} -> {asset_id}")

        print("\n=== 3. Step two: chain that id into the next tool ===")
        now = datetime.now(UTC)
        step2 = await invoker.invoke(
            "get_alarm_summary",
            {
                "asset_ids": [asset_id],  # <-- the value step one produced
                "start_time": (now - timedelta(days=90)).isoformat(),
                "end_time": now.isoformat(),
                "severity": ["high", "critical"],
                "group_by": ["alarm_name"],
                "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay"],
            },
            trace_id=trace_id,
        )
        if not step2.ok:
            print(f"  FAILED: {step2.error_code} {step2.error_message}")
            return 1
        summary = step2.output or {}
        print(f"  {step2.summary()}")
        print(f"  {summary['total_alarms']} high/critical alarms in the last 90 days")
        for group in summary["groups"][:3]:
            name = group["group"].get("alarm_name", "?")
            print(f"    {name:32s} {group['kpis']}")

        print("\n=== 4. Cross-server step ===")
        step3 = await invoker.invoke(
            "search_issues", {"query": asset["asset_name"], "limit": 5}, trace_id=trace_id
        )
        print(f"  {step3.summary()}")
        if step3.ok:
            print(f"  existing issues found: {(step3.output or {})['count']}")

        print("\n=== 5. Failure handling ===")
        bad = await invoker.invoke("search_assets", {"limit": 5}, trace_id=trace_id)
        print(f"  missing required argument -> {bad.error_code} (rejected before the network)")
        missing = await invoker.invoke("no_such_tool", {}, trace_id=trace_id)
        print(f"  unknown tool             -> {missing.error_code}")

        print("\n=== Trace ===")
        for label, result in (("s1", step1), ("s2", step2), ("s3", step3)):
            print(
                f"  {label}: {result.server}/{result.tool} "
                f"{result.duration_ms:6.1f}ms trace_id={result.trace_id}"
            )
        print("\nChaining works: step two consumed the asset_id step one produced.\n")
        return 0
    finally:
        await registry.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--http", action="store_true", help="use running MCP servers instead of in-process"
    )
    raise SystemExit(asyncio.run(main(parser.parse_args().http)))
