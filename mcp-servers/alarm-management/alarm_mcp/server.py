"""Alarm Management MCP server.

Exposes the Alarm Management API as 14 typed MCP tools. Runs standalone::

    python -m alarm_mcp                      # stdio, for a local MCP client
    python -m alarm_mcp --transport http     # streamable HTTP, for docker compose

Two properties are deliberate and load-bearing:

**No tool accepts a credential.** The bearer token is read from configuration into
the connector at startup. It is not a parameter of any tool, so a language model
driving this server cannot read it, cannot be persuaded to reveal it, and cannot
leak it through an argument. This is the reason the MCP boundary exists.

**Tool descriptions are written for a model to read.** They are part of the product,
not documentation: the planner selects tools from these strings, so a vague
description produces a wrong plan no amount of downstream validation can repair.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from alarm_api import AlarmApiClient
from copilot_schemas.alarm_tools import (
    AlarmCorrelationOutput,
    AlarmSummaryOutput,
    AlarmTrendsOutput,
    AssetMetadataOutput,
    Bucket,
    CalculationType,
    ExecuteCalculationOutput,
    FloodAnalysisOutput,
    GenerateCalculationOutput,
    GetAlarmOutput,
    GetAlarmsOutput,
    GroupBy,
    KpiDefinitionsOutput,
    KpiName,
    OperatorActionsOutput,
    PriorityScoreOutput,
    RationalizationOutput,
    SearchAssetsOutput,
    Severity,
    SortBy,
    SortOrder,
    ToolMeta,
    TrendMetric,
)
from mcp.server import MCPServer
from pydantic import Field

from .config import Settings, get_settings
from .logging import configure_logging, get_logger
from .mapping import tool_errors

logger = get_logger(__name__)

mcp = MCPServer(
    name="alarm-management",
    version="1.0.0",
    instructions=(
        "Read-only access to plant alarm and asset data. Resolve an asset by name with "
        "search_assets first, then pass the returned asset_id to the analysis tools. "
        "For questions about why alarms recur, combine get_alarm_summary (how often), "
        "get_alarm_correlation (what fires alongside), and "
        "get_rationalization_candidates (what should be re-tuned)."
    ),
)

_client: AlarmApiClient | None = None


def get_client(settings: Settings | None = None) -> AlarmApiClient:
    """Lazily construct the shared connector.

    One client per process so httpx connection pooling actually applies; building a
    client per call would open a new connection for every tool invocation.
    """
    global _client
    if _client is None:
        settings = settings or get_settings()
        _client = AlarmApiClient(
            base_url=settings.alarm_api_base_url,
            token=settings.alarm_api_token,
            timeout_seconds=settings.alarm_api_timeout_seconds,
            max_retries=settings.alarm_api_max_retries,
            client_id=settings.mcp_client_id,
        )
    return _client


def set_client(client: AlarmApiClient | None) -> None:
    """Replace the shared connector. Used by tests to inject a mock transport."""
    global _client
    _client = client


def _trace(trace_id: str | None) -> str:
    """Use the caller's trace id, or mint one so nothing is untraceable."""
    return trace_id or f"trace-{uuid.uuid4().hex[:12]}"


def _meta(trace_id: str) -> ToolMeta:
    return ToolMeta(trace_id=trace_id)


def _time_range(start_time: str | None, end_time: str | None) -> dict[str, str] | None:
    if start_time and end_time:
        return {"start_time": start_time, "end_time": end_time}
    return None


def _scope(
    asset_ids: list[str] | None, unit: str | None, site: str | None
) -> dict[str, Any]:
    """Build the scope portion of an analytical request body."""
    return {"asset_ids": asset_ids, "unit": unit, "site": site}


# Reused parameter annotations. Defining them once keeps 14 tool signatures
# consistent and means a wording improvement lands everywhere at once.
TraceId = Annotated[
    str | None,
    Field(description="Correlation id to propagate to the source system. Generated if omitted."),
]
StartTime = Annotated[
    str | None, Field(description="ISO-8601 window start, e.g. 2026-05-15T00:00:00Z")
]
EndTime = Annotated[str | None, Field(description="ISO-8601 window end")]
AssetIds = Annotated[
    list[str] | None,
    Field(description="Asset ids from search_assets. Omit to scope by unit or site instead."),
]
Unit = Annotated[str | None, Field(description="Plant unit, e.g. 'Unit 2'")]
Site = Annotated[str | None, Field(description="Plant site, e.g. 'NorthPlant'")]


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #


@mcp.tool()
@tool_errors("search_assets")
async def search_assets(
    query: Annotated[
        str, Field(description="Free text matched against asset name and type, "
                               "e.g. 'Boiler Feed Pump 101' or 'compressor'")
    ],
    limit: Annotated[int, Field(description="Maximum results", ge=1, le=100)] = 10,
    unit: Unit = None,
    trace_id: TraceId = None,
) -> SearchAssetsOutput:
    """Resolve a free-text asset name or type to structured asset records.

    Start here for any question that names equipment. Almost every other tool needs
    an asset_id, and this is the only tool that produces one from a human name.
    Matching is case-insensitive and partial, so 'compressor' returns every
    compressor.
    """
    trace = _trace(trace_id)
    payload = await get_client().search_assets(query, limit=limit, unit=unit, trace_id=trace)
    return SearchAssetsOutput(**payload, meta=_meta(trace))


@mcp.tool()
@tool_errors("get_asset_metadata")
async def get_asset_metadata(
    asset_id: Annotated[str, Field(description="Asset id from search_assets, e.g. AST-0005")],
    trace_id: TraceId = None,
) -> AssetMetadataOutput:
    """Full attributes for one asset, plus its current alarm counts.

    Use when the answer depends on what the equipment *is* — its criticality,
    manufacturer, install date, or how long since it was last maintained.
    """
    trace = _trace(trace_id)
    payload = await get_client().get_asset_metadata(asset_id, trace_id=trace)
    return AssetMetadataOutput(**payload, meta=_meta(trace))


# --------------------------------------------------------------------------- #
# Alarm retrieval
# --------------------------------------------------------------------------- #


@mcp.tool()
@tool_errors("get_alarms")
async def get_alarms(
    asset_id: Annotated[str | None, Field(description="Restrict to one asset")] = None,
    unit: Unit = None,
    site: Site = None,
    status: Annotated[
        str | None, Field(description="One of: active, acknowledged, cleared")
    ] = None,
    severity: Annotated[
        str | None, Field(description="One of: low, medium, high, critical")
    ] = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    page: Annotated[int, Field(description="One-based page number", ge=1)] = 1,
    page_size: Annotated[int, Field(description="Rows per page, capped at 500", ge=1)] = 50,
    sort_by: SortBy = "start_time",
    sort_order: SortOrder = "desc",
    trace_id: TraceId = None,
) -> GetAlarmsOutput:
    """List individual alarms with filtering, sorting, and pagination.

    Use when the question is about specific alarm occurrences — 'what is active right
    now', 'the most recent alarm on this pump'. For counts, rates, or patterns use
    get_alarm_summary instead; it aggregates server-side rather than making you page
    through rows.

    The response reports total_count and has_next, so check those before concluding
    a list is complete.
    """
    trace = _trace(trace_id)
    payload = await get_client().get_alarms(
        asset_id=asset_id, unit=unit, site=site, status=status, severity=severity,
        start_time=start_time, end_time=end_time, page=page, page_size=page_size,
        sort_by=sort_by, sort_order=sort_order, trace_id=trace,
    )
    return GetAlarmsOutput(**payload, meta=_meta(trace))


@mcp.tool()
@tool_errors("get_alarm_by_id")
async def get_alarm_by_id(
    alarm_id: Annotated[str, Field(description="Alarm id, e.g. ALM-00069")],
    trace_id: TraceId = None,
) -> GetAlarmOutput:
    """Retrieve the full detail of one alarm by its id.

    Returns the process value that triggered it and the setpoint it crossed, the
    acknowledgement time and delay, and the current status. Use after get_alarms has
    identified an alarm of interest, or when another tool has returned an alarm_id
    you need the full record for.
    """
    trace = _trace(trace_id)
    payload = await get_client().get_alarm(alarm_id, trace_id=trace)
    return GetAlarmOutput(alarm=payload, meta=_meta(trace))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


@mcp.tool()
@tool_errors("get_alarm_summary")
async def get_alarm_summary(
    asset_ids: AssetIds = None,
    unit: Unit = None,
    site: Site = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    severity: Annotated[
        list[Severity] | None, Field(description="Restrict to these severities")
    ] = None,
    alarm_types: Annotated[list[str] | None, Field(description="e.g. ['safety','device']")] = None,
    group_by: Annotated[
        list[GroupBy], Field(description="Dimensions to group by")
    ] = ["alarm_name"],  # noqa: B006 — MCP needs a literal default in the schema
    kpis: Annotated[list[KpiName], Field(description="KPIs to compute per group")] = [  # noqa: B006
        "alarm_count"
    ],
    trace_id: TraceId = None,
) -> AlarmSummaryOutput:
    """Aggregate alarms into groups and compute KPIs for each.

    The main tool for 'how often', 'how many', and 'which alarm dominates'. Grouping
    by alarm_name answers what recurs; grouping by asset_id answers which equipment
    is worst.

    KPIs available: alarm_count, critical_count, avg_ack_delay (mean seconds to
    acknowledge), recurring_rate (share of alarms that repeat a name already seen,
    where values near 1.0 mean a handful of alarms firing over and over), and
    suppression_candidate_rate.
    """
    trace = _trace(trace_id)
    body = {
        **_scope(asset_ids, unit, site),
        "time_range": _time_range(start_time, end_time),
        "severity": severity,
        "alarm_types": alarm_types,
        "group_by": group_by,
        "kpis": kpis,
    }
    payload = await get_client().alarm_summary(
        {k: v for k, v in body.items() if v is not None}, trace_id=trace
    )
    return AlarmSummaryOutput(
        total_alarms=payload["total_alarms"], groups=payload["groups"], meta=_meta(trace)
    )


@mcp.tool()
@tool_errors("get_alarm_trends")
async def get_alarm_trends(
    asset_ids: AssetIds = None,
    unit: Unit = None,
    site: Site = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    bucket: Bucket = "daily",
    metrics: Annotated[list[TrendMetric], Field(description="Metrics per bucket")] = [  # noqa: B006
        "alarm_count"
    ],
    trace_id: TraceId = None,
) -> AlarmTrendsOutput:
    """Alarm metrics bucketed over time.

    Use when the question is about direction — is this getting worse, did it change
    after an intervention, when did it start. For a single total, use
    get_alarm_summary instead.
    """
    trace = _trace(trace_id)
    body = {
        **_scope(asset_ids, unit, site),
        "time_range": _time_range(start_time, end_time),
        "bucket": bucket,
        "metrics": metrics,
    }
    payload = await get_client().alarm_trends(
        {k: v for k, v in body.items() if v is not None}, trace_id=trace
    )
    return AlarmTrendsOutput(
        bucket=payload["bucket"], points=payload["points"], meta=_meta(trace)
    )


@mcp.tool()
@tool_errors("get_alarm_correlation")
async def get_alarm_correlation(
    asset_ids: AssetIds = None,
    unit: Unit = None,
    site: Site = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    lag_window_minutes: Annotated[
        int, Field(description="How close in time two alarms must be to count", ge=1, le=1440)
    ] = 15,
    severity_threshold: Annotated[
        Severity, Field(description="Consider only this severity and above")
    ] = "medium",
    min_support: Annotated[
        int, Field(description="Minimum co-occurrences before a pair is reported", ge=1)
    ] = 1,
    trace_id: TraceId = None,
) -> AlarmCorrelationOutput:
    """Find which alarms tend to fire together, and how strongly.

    The primary tool for 'what is causing this' and 'what else happens at the same
    time'. Co-occurrence is measured within a single asset, so a reported pair is a
    real relationship on that equipment rather than two unrelated events coinciding.

    Read `lift` before `support`: support counts how often the pair occurred, but
    lift says whether that is more than chance. Lift near 1.0 means no real
    association however large the support; above 1.0 indicates a genuine link.
    """
    trace = _trace(trace_id)
    body = {
        **_scope(asset_ids, unit, site),
        "time_range": _time_range(start_time, end_time),
        "correlation_method": "cooccurrence",
        "lag_window_minutes": lag_window_minutes,
        "severity_threshold": severity_threshold,
        "min_support": min_support,
    }
    payload = await get_client().alarm_correlation(
        {k: v for k, v in body.items() if v is not None}, trace_id=trace
    )
    return AlarmCorrelationOutput(
        correlation_method=payload["correlation_method"],
        lag_window_minutes=payload["lag_window_minutes"],
        pairs=payload["pairs"],
        meta=_meta(trace),
    )


@mcp.tool()
@tool_errors("get_flood_analysis")
async def get_flood_analysis(
    unit: Unit = None,
    site: Site = None,
    asset_ids: AssetIds = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    threshold_count: Annotated[
        int, Field(description="Alarms within the window that constitute a flood", ge=1)
    ] = 10,
    rolling_window_minutes: Annotated[
        int, Field(description="Width of the rolling window", ge=1, le=1440)
    ] = 10,
    trace_id: TraceId = None,
) -> FloodAnalysisOutput:
    """Find periods where alarms arrived faster than an operator could process them.

    Alarm flooding is a recognised failure mode: during a flood the operator cannot
    read, let alone act on, what the console is showing, so genuinely important
    alarms get missed. Each returned window reports its span, how many alarms it
    contained, which assets contributed, and the dominant alarm name.

    Overlapping detections are merged, so one burst produces one window.
    """
    trace = _trace(trace_id)
    body = {
        **_scope(asset_ids, unit, site),
        "time_range": _time_range(start_time, end_time),
        "threshold_count": threshold_count,
        "rolling_window_minutes": rolling_window_minutes,
    }
    payload = await get_client().flood_analysis(
        {k: v for k, v in body.items() if v is not None}, trace_id=trace
    )
    return FloodAnalysisOutput(
        threshold_count=payload["threshold_count"],
        rolling_window_minutes=payload["rolling_window_minutes"],
        flood_windows=payload["flood_windows"],
        meta=_meta(trace),
    )


@mcp.tool()
@tool_errors("get_rationalization_candidates")
async def get_rationalization_candidates(
    asset_ids: AssetIds = None,
    unit: Unit = None,
    site: Site = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    recurrence_threshold: Annotated[
        int, Field(description="Occurrences at or above which an alarm is flagged", ge=1)
    ] = 5,
    stale_minutes_threshold: Annotated[
        int, Field(description="Minutes an alarm may stay active before it is stale", ge=1)
    ] = 180,
    trace_id: TraceId = None,
) -> RationalizationOutput:
    """Identify alarms that should be re-tuned, suppressed, or chased up.

    Two independent triggers, and the distinction matters because they call for
    different remedies. An alarm that *recurs* excessively usually needs its setpoint
    or deadband adjusted. An alarm that sits *stale* — active long past the threshold
    without acknowledgement — points at a workflow or workload problem instead.

    Each candidate carries the reason it was flagged and a recommended remedy.
    """
    trace = _trace(trace_id)
    body = {
        **_scope(asset_ids, unit, site),
        "time_range": _time_range(start_time, end_time),
        "recurrence_threshold": recurrence_threshold,
        "stale_minutes_threshold": stale_minutes_threshold,
    }
    payload = await get_client().rationalization_candidates(
        {k: v for k, v in body.items() if v is not None}, trace_id=trace
    )
    return RationalizationOutput(
        candidates=payload["candidates"],
        recurrence_threshold=payload["recurrence_threshold"],
        stale_minutes_threshold=payload["stale_minutes_threshold"],
        meta=_meta(trace),
    )


@mcp.tool()
@tool_errors("get_priority_score")
async def get_priority_score(
    alarm_id: Annotated[str, Field(description="Alarm id, e.g. ALM-00069")],
    trace_id: TraceId = None,
) -> PriorityScoreOutput:
    """Score one alarm's priority from 0 to 100, with the reasoning broken out.

    Combines alarm severity, asset criticality, how often the alarm recurs, and how
    long it went unacknowledged. Use to rank competing alarms.

    The `factors` array gives each component's weight and contribution. Quote those
    when explaining a ranking rather than restating the score — the breakdown is what
    makes the number defensible.
    """
    trace = _trace(trace_id)
    payload = await get_client().priority_score(alarm_id, trace_id=trace)
    return PriorityScoreOutput(
        alarm_id=payload["alarm_id"],
        priority_score=payload["priority_score"],
        band=payload["band"],
        factors=payload["factors"],
        meta=_meta(trace),
    )


@mcp.tool()
@tool_errors("get_operator_recommendations")
async def get_operator_recommendations(
    alarm_id: Annotated[str, Field(description="Alarm id to advise on")],
    include_related: Annotated[
        bool, Field(description="Include alarms near it in time on the same asset")
    ] = False,
    include_asset_context: Annotated[
        bool, Field(description="Include the asset's attributes")
    ] = False,
    include_historical_pattern: Annotated[
        bool, Field(description="Include 90-day recurrence statistics")
    ] = False,
    trace_id: TraceId = None,
) -> OperatorActionsOutput:
    """Ordered, actionable steps for an operator responding to a specific alarm.

    Each action carries a rationale and its expected outcome, so the advice can be
    presented with its reasoning rather than as a bare list.

    The three include_* flags are opt-in because each costs an extra lookup. Enable
    all three when building a full investigation or an escalation summary.
    """
    trace = _trace(trace_id)
    payload = await get_client().operator_actions(
        {
            "alarm_id": alarm_id,
            "include_related": include_related,
            "include_asset_context": include_asset_context,
            "include_historical_pattern": include_historical_pattern,
        },
        trace_id=trace,
    )
    return OperatorActionsOutput(
        alarm_id=payload["alarm_id"],
        alarm_name=payload["alarm_name"],
        severity=payload["severity"],
        actions=payload["actions"],
        related_alarms=payload.get("related_alarms"),
        asset_context=payload.get("asset_context"),
        historical_pattern=payload.get("historical_pattern"),
        meta=_meta(trace),
    )


# --------------------------------------------------------------------------- #
# Calculations — a deliberate two-step chain
# --------------------------------------------------------------------------- #


@mcp.tool()
@tool_errors("generate_calculation")
async def generate_calculation(
    calculation_type: Annotated[
        CalculationType, Field(description="Which KPI calculation to prepare")
    ],
    unit: Unit = None,
    site: Site = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    trace_id: TraceId = None,
) -> GenerateCalculationOutput:
    """Prepare a KPI calculation and return its identifier.

    Step one of two. This registers the calculation and returns a calculation_id;
    it does not compute anything. Pass that id to execute_calculation to get the
    value. There is no way to run a calculation without calling this first.

    Types: alarm_flood_index (share of alarms arriving during floods),
    critical_alarm_density (critical alarms per asset per day),
    operator_response_efficiency (share acknowledged within five minutes),
    nuisance_alarm_score (share coming from excessively repeating alarm names).
    """
    trace = _trace(trace_id)
    filters = {k: v for k, v in {
        "unit": unit, "site": site, "start_time": start_time, "end_time": end_time
    }.items() if v is not None}
    payload = await get_client().generate_calculation(
        {"calculation_type": calculation_type, "filters": filters}, trace_id=trace
    )
    return GenerateCalculationOutput(
        calculation_id=payload["calculation_id"],
        calculation_type=payload["calculation_type"],
        generated_code=payload["generated_code"],
        meta=_meta(trace),
    )


@mcp.tool()
@tool_errors("execute_calculation")
async def execute_calculation(
    calculation_id: Annotated[
        str, Field(description="The id returned by generate_calculation")
    ],
    unit: Unit = None,
    site: Site = None,
    start_time: StartTime = None,
    end_time: EndTime = None,
    trace_id: TraceId = None,
) -> ExecuteCalculationOutput:
    """Run a prepared calculation and return its value with a supporting table.

    Step two of two — requires a calculation_id from generate_calculation.

    Filters supplied here override those captured at generation, so the same
    calculation can be re-run against a different unit or period without preparing
    it again. The response includes a plain-language interpretation alongside the
    number.
    """
    trace = _trace(trace_id)
    filters = {k: v for k, v in {
        "unit": unit, "site": site, "start_time": start_time, "end_time": end_time
    }.items() if v is not None}
    payload = await get_client().execute_calculation(
        {"calculation_id": calculation_id, "filters": filters}, trace_id=trace
    )
    return ExecuteCalculationOutput(
        calculation_id=payload["calculation_id"],
        calculation_type=payload["calculation_type"],
        value=payload["value"],
        unit=payload["unit"],
        columns=payload["columns"],
        rows=payload["rows"],
        interpretation=payload["interpretation"],
        meta=_meta(trace),
    )


@mcp.tool()
@tool_errors("get_kpi_definitions")
async def get_kpi_definitions(trace_id: TraceId = None) -> KpiDefinitionsOutput:
    """Definitions and formulas for every KPI the summary tool can compute.

    Use when a question asks what a metric means, or when an answer should state how
    a figure was derived. Sourcing the formula from the system avoids restating a
    definition that could drift from the implementation.
    """
    trace = _trace(trace_id)
    payload = await get_client().kpi_definitions(trace_id=trace)
    return KpiDefinitionsOutput(definitions=payload["definitions"], meta=_meta(trace))


def main() -> None:
    """Entry point. Transport is chosen by ``--transport``; default is stdio."""
    import argparse

    parser = argparse.ArgumentParser(description="Alarm Management MCP server")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="stdio for a local MCP client, http for containerised deployment",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "mcp_server_starting",
        mcp_server="alarm-management",
        transport=args.transport,
        upstream=settings.alarm_api_base_url,
        tool_count=14,
    )

    if args.transport == "http":
        mcp.run(
            transport="streamable-http",
            host=settings.mcp_alarm_host,
            port=settings.mcp_alarm_port,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
