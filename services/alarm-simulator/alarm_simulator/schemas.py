"""Request and response contracts for the Alarm Management API.

Derived from the three Postman collections in ``postman/``, which are the
specification. Where a field appears only in the chaining collection it is called
out, because those are the ones easily missed by reading the baseline collection
alone.

Four response field names are load-bearing — the collections' test scripts assert
on these exact paths, so renaming any of them breaks the contract check:

* ``AssetSearchResponse.results[].asset_id``
* ``AlarmListResponse.data[].alarm_id``
* ``CalculationGenerateResponse.calculation_id``
* ``FloodAnalysisResponse.flood_windows[].start`` / ``.end``
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Enumerations — every value observed across the three collections
# --------------------------------------------------------------------------- #


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlarmStatus(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    CLEARED = "cleared"


class AlarmType(StrEnum):
    PROCESS = "process"
    SAFETY = "safety"
    DEVICE = "device"
    SYSTEM = "system"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GroupBy(StrEnum):
    ALARM_NAME = "alarm_name"
    ASSET_ID = "asset_id"
    ASSET_NAME = "asset_name"
    SEVERITY = "severity"


class Kpi(StrEnum):
    ALARM_COUNT = "alarm_count"
    RECURRING_RATE = "recurring_rate"
    AVG_ACK_DELAY = "avg_ack_delay"
    CRITICAL_COUNT = "critical_count"
    SUPPRESSION_CANDIDATE_RATE = "suppression_candidate_rate"


class TrendMetric(StrEnum):
    ALARM_COUNT = "alarm_count"
    AVG_ACK_DELAY = "avg_ack_delay"


class Bucket(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class CorrelationMethod(StrEnum):
    COOCCURRENCE = "cooccurrence"


class CalculationType(StrEnum):
    ALARM_FLOOD_INDEX = "alarm_flood_index"
    CRITICAL_ALARM_DENSITY = "critical_alarm_density"
    OPERATOR_RESPONSE_EFFICIENCY = "operator_response_efficiency"
    NUISANCE_ALARM_SCORE = "nuisance_alarm_score"


class SortBy(StrEnum):
    START_TIME = "start_time"
    SEVERITY = "severity"
    ALARM_NAME = "alarm_name"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


# Severity ordering, used by `severity_threshold` filters which mean
# "this level and above".
SEVERITY_RANK: dict[str, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #


class TimeRange(BaseModel):
    """An inclusive-start, exclusive-end window."""

    start_time: datetime
    end_time: datetime


class TraceEnvelope(BaseModel):
    """Trace context echoed on analytical responses.

    Present so a caller can confirm propagation from the response body alone,
    without inspecting headers.
    """

    trace_id: str | None = None
    client_id: str | None = None
    metadata_tag: str | None = None


# --------------------------------------------------------------------------- #
# 00 — Health
# --------------------------------------------------------------------------- #


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "alarm-management-api"
    version: str
    asset_count: int
    alarm_count: int


# --------------------------------------------------------------------------- #
# 01/02 — Assets
# --------------------------------------------------------------------------- #


class AssetSummary(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    unit: str
    site: str
    criticality: str


class AssetSearchResponse(BaseModel):
    """``results`` is asserted by the collections — do not rename."""

    query: str
    count: int
    results: list[AssetSummary]


class AssetMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: str
    asset_name: str
    asset_type: str
    unit: str
    site: str
    criticality: str
    manufacturer: str
    model: str
    install_date: datetime
    last_maintenance: datetime | None
    total_alarms: int
    active_alarms: int


# --------------------------------------------------------------------------- #
# 03/04 — Alarms
# --------------------------------------------------------------------------- #


class AlarmRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alarm_id: str
    asset_id: str
    asset_name: str | None = None
    alarm_name: str
    alarm_type: str
    severity: str
    status: str
    start_time: datetime
    end_time: datetime | None
    ack_time: datetime | None
    ack_delay_seconds: int | None
    value: float | None
    setpoint: float | None
    unit_of_measure: str | None
    operator_id: str | None


class AlarmListResponse(BaseModel):
    """``data`` is asserted by the collections — do not rename."""

    data: list[AlarmRecord]
    page: int
    page_size: int
    total_count: int
    has_next: bool


# --------------------------------------------------------------------------- #
# 05 — Summary
# --------------------------------------------------------------------------- #


class AlarmSummaryRequest(BaseModel):
    asset_ids: list[str] | None = None
    # `unit`, `site` and `alarm_types` appear only in the chaining collection.
    unit: str | None = None
    site: str | None = None
    alarm_types: list[AlarmType] | None = None
    time_range: TimeRange | None = None
    severity: list[Severity] | None = None
    group_by: list[GroupBy] = Field(default_factory=lambda: [GroupBy.ALARM_NAME])
    kpis: list[Kpi] = Field(default_factory=lambda: [Kpi.ALARM_COUNT])


class SummaryGroup(BaseModel):
    group: dict[str, str]
    kpis: dict[str, float]


class AlarmSummaryResponse(BaseModel):
    total_alarms: int
    groups: list[SummaryGroup]
    time_range: TimeRange | None
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 06 — Trends
# --------------------------------------------------------------------------- #


class AlarmTrendsRequest(BaseModel):
    asset_ids: list[str] | None = None
    unit: str | None = None
    site: str | None = None
    time_range: TimeRange | None = None
    bucket: Bucket = Bucket.DAILY
    metrics: list[TrendMetric] = Field(default_factory=lambda: [TrendMetric.ALARM_COUNT])


class TrendPoint(BaseModel):
    bucket_start: datetime
    metrics: dict[str, float]


class AlarmTrendsResponse(BaseModel):
    bucket: str
    points: list[TrendPoint]
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 07 — Correlation
# --------------------------------------------------------------------------- #


class AlarmCorrelationRequest(BaseModel):
    asset_ids: list[str] | None = None
    unit: str | None = None
    site: str | None = None
    time_range: TimeRange | None = None
    correlation_method: CorrelationMethod = CorrelationMethod.COOCCURRENCE
    lag_window_minutes: int = Field(default=15, ge=1, le=1440)
    severity_threshold: Severity = Severity.MEDIUM
    min_support: int = Field(default=1, ge=1)


class CorrelationPair(BaseModel):
    alarm_a: str
    alarm_b: str
    support: int
    confidence: float
    lift: float
    mean_lag_seconds: float


class AlarmCorrelationResponse(BaseModel):
    correlation_method: str
    lag_window_minutes: int
    pairs: list[CorrelationPair]
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 08 — Flood analysis
# --------------------------------------------------------------------------- #


class FloodAnalysisRequest(BaseModel):
    unit: str | None = None
    site: str | None = None
    asset_ids: list[str] | None = None
    time_range: TimeRange | None = None
    threshold_count: int = Field(default=10, ge=1)
    rolling_window_minutes: int = Field(default=10, ge=1, le=1440)


class FloodWindow(BaseModel):
    """``start`` and ``end`` are asserted by CHAIN-02 — do not rename."""

    start: datetime
    end: datetime
    alarm_count: int
    peak_rate_per_minute: float
    contributing_assets: list[str]
    dominant_alarm_name: str | None


class FloodAnalysisResponse(BaseModel):
    threshold_count: int
    rolling_window_minutes: int
    flood_windows: list[FloodWindow]
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 09 — Rationalization
# --------------------------------------------------------------------------- #


class RationalizationRequest(BaseModel):
    asset_ids: list[str] | None = None
    unit: str | None = None
    site: str | None = None
    time_range: TimeRange | None = None
    recurrence_threshold: int = Field(default=5, ge=1)
    stale_minutes_threshold: int = Field(default=180, ge=1)


class RationalizationCandidate(BaseModel):
    asset_id: str
    asset_name: str
    alarm_name: str
    occurrences: int
    stale_count: int
    reason: str
    recommendation: str


class RationalizationResponse(BaseModel):
    candidates: list[RationalizationCandidate]
    recurrence_threshold: int
    stale_minutes_threshold: int
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 10 — Priority score
# --------------------------------------------------------------------------- #


class PriorityScoreRequest(BaseModel):
    alarm_id: str


class PriorityFactor(BaseModel):
    factor: str
    weight: float
    raw_value: float
    contribution: float
    explanation: str


class PriorityScoreResponse(BaseModel):
    alarm_id: str
    priority_score: float
    band: str
    factors: list[PriorityFactor]
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 11 — Operator recommendations
# --------------------------------------------------------------------------- #


class OperatorActionsRequest(BaseModel):
    alarm_id: str
    include_related: bool = False
    include_asset_context: bool = False
    include_historical_pattern: bool = False


class RecommendedAction(BaseModel):
    order: int
    action: str
    rationale: str
    expected_outcome: str


class HistoricalPattern(BaseModel):
    occurrences_90d: int
    mean_interval_hours: float | None
    typical_ack_delay_seconds: float | None
    is_recurring: bool


class OperatorActionsResponse(BaseModel):
    alarm_id: str
    alarm_name: str
    severity: str
    actions: list[RecommendedAction]
    related_alarms: list[AlarmRecord] | None = None
    asset_context: AssetMetadataResponse | None = None
    historical_pattern: HistoricalPattern | None = None
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 12/13 — Calculation code
# --------------------------------------------------------------------------- #


class CalculationGenerateRequest(BaseModel):
    calculation_type: CalculationType
    filters: dict[str, Any] = Field(default_factory=dict)


class CalculationGenerateResponse(BaseModel):
    """``calculation_id`` is asserted by the collections — do not rename."""

    calculation_id: str
    calculation_type: str
    generated_code: str
    filters: dict[str, Any]
    created_at: datetime


class CalculationExecuteRequest(BaseModel):
    calculation_id: str
    filters: dict[str, Any] = Field(default_factory=dict)


class CalculationExecuteResponse(BaseModel):
    calculation_id: str
    calculation_type: str
    value: float
    unit: str
    columns: list[str]
    rows: list[list[Any]]
    interpretation: str
    trace: TraceEnvelope


# --------------------------------------------------------------------------- #
# 14 — KPI definitions
# --------------------------------------------------------------------------- #


class KpiDefinition(BaseModel):
    name: str
    display_name: str
    description: str
    formula: str
    unit: str


class KpiDefinitionsResponse(BaseModel):
    definitions: list[KpiDefinition]
