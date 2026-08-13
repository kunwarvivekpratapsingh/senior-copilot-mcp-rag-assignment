"""Typed contracts for the alarm-management MCP tools.

These are the **MCP tool** contracts, defined independently of the simulator's
internal schemas. The MCP server codes against the published HTTP contract, not
against the source system's internals — if the two were the same module, a refactor
inside the simulator could silently change the tool surface the copilot depends on.

Every tool has a typed input model and a typed output model. The input model is what
makes invalid arguments fail before any network call; the output model is what the
GUI's schema inspector renders.

Each output carries a :class:`ToolMeta` so the orchestrator can show which trace id
the call ran under without a second lookup.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
AlarmStatus = Literal["active", "acknowledged", "cleared"]
AlarmType = Literal["process", "safety", "device", "system"]
GroupBy = Literal["alarm_name", "asset_id", "asset_name", "severity"]
KpiName = Literal[
    "alarm_count", "recurring_rate", "avg_ack_delay",
    "critical_count", "suppression_candidate_rate",
]
TrendMetric = Literal["alarm_count", "avg_ack_delay"]
Bucket = Literal["hourly", "daily", "weekly"]
CalculationType = Literal[
    "alarm_flood_index", "critical_alarm_density",
    "operator_response_efficiency", "nuisance_alarm_score",
]
SortBy = Literal["start_time", "severity", "alarm_name"]
SortOrder = Literal["asc", "desc"]


class ToolMeta(BaseModel):
    """Execution metadata attached to every tool result."""

    trace_id: str = Field(description="Correlation id propagated to the source system")
    source: str = Field(default="alarm-management-api", description="System that answered")


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #


class AssetSummary(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    unit: str
    site: str
    criticality: str


class SearchAssetsOutput(BaseModel):
    query: str
    count: int
    results: list[AssetSummary]
    meta: ToolMeta


class AssetMetadataOutput(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    unit: str
    site: str
    criticality: str
    manufacturer: str
    model: str
    install_date: str
    last_maintenance: str | None
    total_alarms: int
    active_alarms: int
    meta: ToolMeta


# --------------------------------------------------------------------------- #
# Alarms
# --------------------------------------------------------------------------- #


class AlarmRecord(BaseModel):
    alarm_id: str
    asset_id: str
    asset_name: str | None = None
    alarm_name: str
    alarm_type: str
    severity: str
    status: str
    start_time: str
    end_time: str | None = None
    ack_time: str | None = None
    ack_delay_seconds: int | None = None
    value: float | None = None
    setpoint: float | None = None
    unit_of_measure: str | None = None
    operator_id: str | None = None


class GetAlarmsOutput(BaseModel):
    data: list[AlarmRecord]
    page: int
    page_size: int
    total_count: int
    has_next: bool
    meta: ToolMeta


class GetAlarmOutput(BaseModel):
    alarm: AlarmRecord
    meta: ToolMeta


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class SummaryGroup(BaseModel):
    group: dict[str, str]
    kpis: dict[str, float]


class AlarmSummaryOutput(BaseModel):
    total_alarms: int
    groups: list[SummaryGroup]
    meta: ToolMeta


class TrendPoint(BaseModel):
    bucket_start: str
    metrics: dict[str, float]


class AlarmTrendsOutput(BaseModel):
    bucket: str
    points: list[TrendPoint]
    meta: ToolMeta


class CorrelationPair(BaseModel):
    alarm_a: str
    alarm_b: str
    support: int = Field(description="Times the pair co-occurred inside the lag window")
    confidence: float = Field(description="Given alarm_a fired, how often alarm_b followed")
    lift: float = Field(
        description="Association strength versus chance. Above 1.0 indicates a real "
        "relationship; near 1.0 means the pair is no more related than coincidence."
    )
    mean_lag_seconds: float


class AlarmCorrelationOutput(BaseModel):
    correlation_method: str
    lag_window_minutes: int
    pairs: list[CorrelationPair]
    meta: ToolMeta


class FloodWindow(BaseModel):
    start: str
    end: str
    alarm_count: int
    peak_rate_per_minute: float
    contributing_assets: list[str]
    dominant_alarm_name: str | None = None


class FloodAnalysisOutput(BaseModel):
    threshold_count: int
    rolling_window_minutes: int
    flood_windows: list[FloodWindow]
    meta: ToolMeta


class RationalizationCandidate(BaseModel):
    asset_id: str
    asset_name: str
    alarm_name: str
    occurrences: int
    stale_count: int
    reason: str
    recommendation: str


class RationalizationOutput(BaseModel):
    candidates: list[RationalizationCandidate]
    recurrence_threshold: int
    stale_minutes_threshold: int
    meta: ToolMeta


class PriorityFactor(BaseModel):
    factor: str
    weight: float
    raw_value: float
    contribution: float
    explanation: str


class PriorityScoreOutput(BaseModel):
    alarm_id: str
    priority_score: float
    band: str
    factors: list[PriorityFactor] = Field(
        description="Per-factor breakdown, so a ranking can be explained rather than asserted"
    )
    meta: ToolMeta


class RecommendedAction(BaseModel):
    order: int
    action: str
    rationale: str
    expected_outcome: str


class HistoricalPattern(BaseModel):
    occurrences_90d: int
    mean_interval_hours: float | None = None
    typical_ack_delay_seconds: float | None = None
    is_recurring: bool


class OperatorActionsOutput(BaseModel):
    alarm_id: str
    alarm_name: str
    severity: str
    actions: list[RecommendedAction]
    related_alarms: list[AlarmRecord] | None = None
    asset_context: dict[str, Any] | None = None
    historical_pattern: HistoricalPattern | None = None
    meta: ToolMeta


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #


class GenerateCalculationOutput(BaseModel):
    calculation_id: str = Field(
        description="Pass this to execute_calculation. The value does not exist until "
        "this tool has run, which is what makes the pair a genuine chain."
    )
    calculation_type: str
    generated_code: str = Field(description="For display only; never executed")
    meta: ToolMeta


class ExecuteCalculationOutput(BaseModel):
    calculation_id: str
    calculation_type: str
    value: float
    unit: str
    columns: list[str]
    rows: list[list[Any]]
    interpretation: str
    meta: ToolMeta


class KpiDefinition(BaseModel):
    name: str
    display_name: str
    description: str
    formula: str
    unit: str


class KpiDefinitionsOutput(BaseModel):
    definitions: list[KpiDefinition]
    meta: ToolMeta
