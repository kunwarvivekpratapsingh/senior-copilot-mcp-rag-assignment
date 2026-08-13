"""Generate ``docs/mcp-tool-catalog.md`` from the running MCP servers.

    python scripts/gen_tool_catalog.py           # write the catalog
    python scripts/gen_tool_catalog.py --check   # fail if it is out of date

The catalog is generated rather than written because a hand-maintained one drifts
from the code the first time a parameter changes, and a tool catalog that lies is
worse than none. Everything here comes from a live ``list_tools()`` against both
servers — the same call the copilot makes at startup.

Example responses are real: each example is produced by actually invoking the tool
against the seeded simulator, in-process. Ids that must come from an earlier call
(an asset id, an alarm id, a calculation id) are resolved first and substituted, so
the examples form a runnable chain rather than plausible-looking fiction.

The generated file is committed. CI runs ``--check``, so a schema change that is not
reflected in the docs fails the build.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from alarm_api import AlarmApiClient
from alarm_mcp.server import mcp as alarm_server
from alarm_mcp.server import set_client
from alarm_simulator.main import app as simulator_app
from copilot_backend.mcp_client import McpServerConfig, ToolInvoker, ToolRegistry
from github_mcp.server import mcp as github_server

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "mcp-tool-catalog.md"
MAX_RESPONSE_CHARS = 1400

# Which upstream operation each tool performs. Not derivable from the schema, and one
# of the ten fields the submission guidelines require per tool.
UPSTREAM: dict[str, str] = {
    "search_assets": "GET /assets/search",
    "get_asset_metadata": "GET /assets/{asset_id}/metadata",
    "get_alarms": "GET /alarms",
    "get_alarm_by_id": "GET /alarms/{alarm_id}",
    "get_alarm_summary": "POST /alarms/summary",
    "get_alarm_trends": "POST /alarms/trends",
    "get_alarm_correlation": "POST /alarms/correlation",
    "get_flood_analysis": "POST /alarms/flood-analysis",
    "get_rationalization_candidates": "POST /alarms/rationalization-candidates",
    "get_priority_score": "GET /alarms/{alarm_id}/priority-score",
    "get_operator_recommendations": "POST /recommendations/operator-actions",
    "generate_calculation": "POST /calculations/generate",
    "execute_calculation": "POST /calculations/execute",
    "get_kpi_definitions": "GET /analytics/kpi-definitions",
    "search_issues": "GET /search/issues (mock backend by default)",
    "draft_issue": "none — a pure function, no I/O",
    "create_issue": "POST /repos/{owner}/{repo}/issues (mock backend by default)",
}

WRITE_TOOLS = {"create_issue"}

# Arguments used to produce each example. Placeholders are filled from earlier calls.
EXAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "search_assets": {"query": "Boiler Feed Pump 101", "limit": 3},
    "get_asset_metadata": {"asset_id": "{asset_id}"},
    "get_alarms": {"asset_id": "{asset_id}", "page_size": 2},
    "get_alarm_by_id": {"alarm_id": "{alarm_id}"},
    "get_alarm_summary": {
        "asset_ids": ["{asset_id}"], "start_time": "{start}", "end_time": "{end}",
        "severity": ["high", "critical"], "group_by": ["alarm_name"],
        "kpis": ["alarm_count", "recurring_rate"],
    },
    "get_alarm_trends": {
        "asset_ids": ["{asset_id}"], "start_time": "{start}", "end_time": "{end}",
        "bucket": "daily", "metrics": ["alarm_count"],
    },
    "get_alarm_correlation": {
        "asset_ids": ["{asset_id}"], "start_time": "{start}", "end_time": "{end}",
        "min_support": 3,
    },
    "get_flood_analysis": {
        "unit": "Unit 2", "start_time": "{start}", "end_time": "{end}",
        "threshold_count": 10, "rolling_window_minutes": 10,
    },
    "get_rationalization_candidates": {
        "asset_ids": ["{asset_id}"], "start_time": "{start}", "end_time": "{end}",
        "recurrence_threshold": 5,
    },
    "get_priority_score": {"alarm_id": "{alarm_id}"},
    "get_operator_recommendations": {
        "alarm_id": "{alarm_id}", "include_related": True, "include_asset_context": True,
    },
    "generate_calculation": {
        "calculation_type": "operator_response_efficiency", "site": "SouthPlant",
        "start_time": "{start}", "end_time": "{end}",
    },
    "execute_calculation": {"calculation_id": "{calculation_id}"},
    "get_kpi_definitions": {},
    "search_issues": {"query": "Boiler Feed Pump 101", "limit": 3},
    "draft_issue": {
        "title": "Recurring suction strainer alarms on Boiler Feed Pump 101",
        "summary": "39 high-severity alarms in 90 days, correlated with discharge pressure low.",
        "labels": ["alarm-rationalization"],
    },
    "create_issue": {
        "title": "Recurring suction strainer alarms on Boiler Feed Pump 101",
        "body": "See the alarm summary and OP-BFP-101 §4.",
        "confirmed": True,
    },
}


def substitute(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format(**context) if "{" in value else value
    if isinstance(value, list):
        return [substitute(v, context) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, context) for k, v in value.items()}
    return value


def fence(payload: Any, *, limit: int | None = None) -> str:
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "\n  … truncated for the catalog"
    return f"```json\n{text}\n```"


@asynccontextmanager
async def simulator_started(app: Any) -> AsyncIterator[None]:
    """Run the simulator's lifespan.

    The ASGI transport reaches the app directly, so its lifespan never runs on its own
    and its database is never created. Entering it explicitly is what puts seeded data
    behind the tools whose examples we are about to capture.
    """
    async with app.router.lifespan_context(app):
        yield


async def build() -> str:
    async with simulator_started(simulator_app):
        return await _build_catalog()


async def _build_catalog() -> str:
    now = datetime.now(UTC)
    set_client(
        AlarmApiClient(
            base_url="http://alarm-simulator",
            token="demo-token",  # noqa: S106 — the documented local demo value
            transport=httpx.ASGITransport(app=simulator_app),
            max_retries=0,
        )
    )
    context = {
        "start": (now - timedelta(days=90)).isoformat(),
        "end": now.isoformat(),
        "asset_id": "",
        "alarm_id": "",
        "calculation_id": "",
    }

    servers = [
        McpServerConfig("alarm-management", alarm_server),
        McpServerConfig("github-issues", github_server),
    ]
    lines: list[str] = []

    async with ToolRegistry(servers=servers) as registry:
        invoker = ToolInvoker(registry=registry)

        # Resolve the ids the later examples depend on, exactly as a plan would.
        assets = await invoker.invoke("search_assets", {"query": "Boiler Feed Pump 101"})
        context["asset_id"] = str((assets.output or {})["results"][0]["asset_id"])
        alarms = await invoker.invoke(
            "get_alarms", {"asset_id": context["asset_id"], "page_size": 1}
        )
        context["alarm_id"] = str((alarms.output or {})["data"][0]["alarm_id"])
        calculation = await invoker.invoke(
            "generate_calculation",
            {"calculation_type": "operator_response_efficiency", "site": "SouthPlant"},
        )
        context["calculation_id"] = str((calculation.output or {})["calculation_id"])

        specs = sorted(registry.specs(), key=lambda s: (s.server, s.name))
        counts: dict[str, int] = {}
        for spec in specs:
            counts[spec.server] = counts.get(spec.server, 0) + 1

        lines += [
            "# MCP Tool Catalog",
            "",
            "<!-- GENERATED FILE — do not edit by hand.",
            "     Regenerate with: python scripts/gen_tool_catalog.py",
            "     CI runs `--check`, so an edited schema with a stale catalog fails. -->",
            "",
            f"{len(specs)} tools across {len(counts)} MCP servers"
            f" ({', '.join(f'{name}: {n}' for name, n in sorted(counts.items()))}).",
            "",
            "Every entry below carries the ten fields the submission guidelines require.",
            "Example responses are real output from the seeded simulator, captured when",
            "this file was generated.",
            "",
            "## Behaviour common to every tool",
            "",
            "| Property | Behaviour |",
            "| --- | --- |",
            "| Authentication | The bearer token is held in the MCP server's configuration"
            " and injected by the connector. **No tool accepts a credential as an"
            " argument**, so a model driving these tools cannot read, leak, or be"
            " persuaded to reveal it. |",
            "| Timeout | 5s per upstream request (`ALARM_API_TIMEOUT_SECONDS`); the MCP"
            " client applies its own 8s ceiling (`MCP_TOOL_TIMEOUT_SECONDS`). |",
            "| Retry | Up to 2 retries with exponential backoff, on 5xx and connection"
            " errors only. A 4xx is never retried — the request was wrong and will stay"
            " wrong. |",
            "| Errors | Returned as `[CODE] message` with a stable code:"
            " `NOT_FOUND`, `INVALID_INPUT`, `AUTH_FAILED`, `UPSTREAM_5XX`, `TIMEOUT`,"
            " `CONFIRMATION_REQUIRED`. The orchestrator branches on the code and shows"
            " the message. |",
            "| Tracing | `trace_id` is accepted, generated when absent, forwarded"
            " upstream, and returned in `meta.trace_id`. |",
            "",
        ]

        for server in sorted(counts):
            lines += [f"## Server: `{server}`", ""]
            for spec in [s for s in specs if s.server == server]:
                args = substitute(EXAMPLE_ARGS.get(spec.name, {}), context)
                result = await invoker.invoke(spec.name, args)
                example = (
                    fence(result.output, limit=MAX_RESPONSE_CHARS)
                    if result.ok
                    else f"_Not captured: `{result.error_code}` — {result.error_message}_"
                )

                lines += [
                    f"### `{spec.name}`",
                    "",
                    f"**Purpose.** {spec.description.strip().splitlines()[0]}",
                    "",
                ]
                remainder = "\n".join(spec.description.strip().splitlines()[1:]).strip()
                if remainder:
                    lines += [remainder, ""]

                lines += [
                    f"**Underlying operation.** `{UPSTREAM.get(spec.name, 'n/a')}`",
                    "",
                    "**Authentication.** Server-held bearer token; never a tool argument."
                    + (
                        "  \n**Write gate.** Refuses with `CONFIRMATION_REQUIRED` unless"
                        " `confirmed: true` is passed, which only an explicit human"
                        " approval sets."
                        if spec.name in WRITE_TOOLS
                        else ""
                    ),
                    "",
                    "**Input schema.**",
                    "",
                    fence(spec.input_schema),
                    "",
                    "**Output schema.**",
                    "",
                    fence(spec.output_schema) if spec.output_schema else "_None declared._",
                    "",
                    "**Example invocation.**",
                    "",
                    fence({"tool": spec.name, "arguments": args}),
                    "",
                    "**Example response.**",
                    "",
                    example,
                    "",
                ]

    set_client(None)
    return "\n".join(lines).rstrip() + "\n"


# Values that legitimately differ between runs. The `--check` gate compares the
# catalog with these normalised away, so it fails on the drift that matters — a
# changed schema, description, or tool list — and not on the clock.
VOLATILE = [
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+\-Z]+"), "<TIMESTAMP>"),
    (re.compile(r"trace-[0-9a-f]{6,}"), "trace-<ID>"),
    (re.compile(r"CALC-[0-9A-Za-z]+"), "CALC-<ID>"),
    # The examples resolve "the most recent alarm", and the seeded window slides with
    # the current date — so this id changes by the day while nothing about the contract
    # does. Asset ids are NOT normalised: those are fixed by the seed, and a change in
    # one would mean the seed generator moved.
    (re.compile(r"ALM-\d+"), "ALM-<ID>"),
    (re.compile(r'"number": \d+'), '"number": <N>'),
    (re.compile(r'"(url|html_url)": "[^"]*"'), r'"\1": "<URL>"'),
]


def normalise(text: str) -> str:
    for pattern, replacement in VOLATILE:
        text = pattern.sub(replacement, text)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="exit non-zero if the committed catalog differs from the generated one",
    )
    args = parser.parse_args(argv)

    catalog = asyncio.run(build())

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if normalise(current) != normalise(catalog):
            print(
                f"{OUTPUT.relative_to(ROOT)} is out of date: a tool, schema, or "
                "description has changed since it was generated.\n"
                "Regenerate it with: python scripts/gen_tool_catalog.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} matches the code.")
        return 0

    OUTPUT.write_text(catalog, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(catalog.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
