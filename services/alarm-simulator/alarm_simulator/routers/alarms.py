"""Alarm retrieval and analytics — endpoints 03 through 10."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .. import analytics
from ..auth import require_bearer_token
from ..config import Settings, get_settings
from ..db import get_session
from ..errors import NotFoundError
from ..models import Alarm, Asset
from ..queries import alarm_history, alarms_in_scope
from ..schemas import (
    AlarmCorrelationRequest,
    AlarmCorrelationResponse,
    AlarmListResponse,
    AlarmRecord,
    AlarmStatus,
    AlarmSummaryRequest,
    AlarmSummaryResponse,
    AlarmTrendsRequest,
    AlarmTrendsResponse,
    FloodAnalysisRequest,
    FloodAnalysisResponse,
    PriorityScoreRequest,
    PriorityScoreResponse,
    RationalizationRequest,
    RationalizationResponse,
    SortBy,
    SortOrder,
    TraceEnvelope,
)
from ..trace import trace_context

router = APIRouter(tags=["alarms"], dependencies=[Depends(require_bearer_token)])


def _trace() -> TraceEnvelope:
    return TraceEnvelope(**trace_context())


def _record(alarm: Alarm, asset_names: dict[str, str]) -> AlarmRecord:
    return AlarmRecord(
        alarm_id=alarm.alarm_id,
        asset_id=alarm.asset_id,
        asset_name=asset_names.get(alarm.asset_id),
        alarm_name=alarm.alarm_name,
        alarm_type=alarm.alarm_type,
        severity=alarm.severity,
        status=alarm.status,
        start_time=alarm.start_time,
        end_time=alarm.end_time,
        ack_time=alarm.ack_time,
        ack_delay_seconds=alarm.ack_delay_seconds,
        value=alarm.value,
        setpoint=alarm.setpoint,
        unit_of_measure=alarm.unit_of_measure,
        operator_id=alarm.operator_id,
    )


# --------------------------------------------------------------------------- #
# 03 — List alarms
# --------------------------------------------------------------------------- #


@router.get("/alarms", response_model=AlarmListResponse)
def list_alarms(
    asset_id: str | None = Query(None),
    unit: str | None = Query(None),
    site: str | None = Query(None),
    status: AlarmStatus | None = Query(None),
    severity: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1),
    sort_by: SortBy = Query(SortBy.START_TIME),
    sort_order: SortOrder = Query(SortOrder.DESC),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AlarmListResponse:
    """Paginated alarm retrieval.

    ``unit``, ``site``, ``status``, ``start_time`` and ``end_time`` appear only in
    the chaining collection, but they are first-class filters here.

    ``page_size`` is clamped rather than rejected: a caller asking for everything
    gets a large page and an honest ``has_next``, instead of an error that would
    break an otherwise valid chain.
    """
    page_size = min(page_size, settings.max_page_size)

    stmt: Select[tuple[Alarm]] = select(Alarm)
    count_stmt = select(func.count()).select_from(Alarm)

    if unit or site:
        asset_stmt = select(Asset.asset_id)
        if unit:
            asset_stmt = asset_stmt.where(Asset.unit == unit)
        if site:
            asset_stmt = asset_stmt.where(Asset.site == site)
        scoped = list(session.execute(asset_stmt).scalars().all())
        stmt = stmt.where(Alarm.asset_id.in_(scoped))
        count_stmt = count_stmt.where(Alarm.asset_id.in_(scoped))

    for clause in (
        (Alarm.asset_id == asset_id) if asset_id else None,
        (Alarm.status == status.value) if status else None,
        (Alarm.severity == severity) if severity else None,
        (Alarm.start_time >= start_time) if start_time else None,
        (Alarm.start_time < end_time) if end_time else None,
    ):
        if clause is not None:
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

    column = {
        SortBy.START_TIME: Alarm.start_time,
        SortBy.SEVERITY: Alarm.severity,
        SortBy.ALARM_NAME: Alarm.alarm_name,
    }[sort_by]
    stmt = stmt.order_by(column.desc() if sort_order == SortOrder.DESC else column.asc())

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    )
    asset_names: dict[str, str] = {
        asset_id: asset_name
        for asset_id, asset_name in session.execute(
            select(Asset.asset_id, Asset.asset_name)
        ).all()
    }

    return AlarmListResponse(
        data=[_record(a, asset_names) for a in rows],
        page=page,
        page_size=page_size,
        total_count=total,
        has_next=(page * page_size) < total,
    )


# --------------------------------------------------------------------------- #
# 04 — Single alarm
# --------------------------------------------------------------------------- #


@router.get("/alarms/{alarm_id}", response_model=AlarmRecord)
def get_alarm(alarm_id: str, session: Session = Depends(get_session)) -> AlarmRecord:
    alarm = session.get(Alarm, alarm_id)
    if alarm is None:
        raise NotFoundError(f"No alarm with id {alarm_id}")
    asset = session.get(Asset, alarm.asset_id)
    return _record(alarm, {alarm.asset_id: asset.asset_name} if asset else {})


# --------------------------------------------------------------------------- #
# 05 — Summary
# --------------------------------------------------------------------------- #


@router.post("/alarms/summary", response_model=AlarmSummaryResponse)
def alarm_summary(
    request: AlarmSummaryRequest, session: Session = Depends(get_session)
) -> AlarmSummaryResponse:
    """Grouped KPI rollup over the selected scope."""
    alarms, assets = alarms_in_scope(
        session,
        asset_ids=request.asset_ids,
        unit=request.unit,
        site=request.site,
        time_range=request.time_range,
        severities=[s.value for s in request.severity] if request.severity else None,
        alarm_types=[t.value for t in request.alarm_types] if request.alarm_types else None,
    )
    groups = analytics.compute_summary(
        alarms, assets, [g.value for g in request.group_by], [k.value for k in request.kpis]
    )
    return AlarmSummaryResponse(
        total_alarms=len(alarms),
        groups=groups,
        time_range=request.time_range,
        trace=_trace(),
    )


# --------------------------------------------------------------------------- #
# 06 — Trends
# --------------------------------------------------------------------------- #


@router.post("/alarms/trends", response_model=AlarmTrendsResponse)
def alarm_trends(
    request: AlarmTrendsRequest, session: Session = Depends(get_session)
) -> AlarmTrendsResponse:
    alarms, _ = alarms_in_scope(
        session,
        asset_ids=request.asset_ids,
        unit=request.unit,
        site=request.site,
        time_range=request.time_range,
    )
    points = analytics.compute_trends(
        alarms, request.bucket.value, [m.value for m in request.metrics]
    )
    return AlarmTrendsResponse(bucket=request.bucket.value, points=points, trace=_trace())


# --------------------------------------------------------------------------- #
# 07 — Correlation
# --------------------------------------------------------------------------- #


@router.post("/alarms/correlation", response_model=AlarmCorrelationResponse)
def alarm_correlation(
    request: AlarmCorrelationRequest, session: Session = Depends(get_session)
) -> AlarmCorrelationResponse:
    """Which alarms tend to fire together, and how strongly."""
    alarms, _ = alarms_in_scope(
        session,
        asset_ids=request.asset_ids,
        unit=request.unit,
        site=request.site,
        time_range=request.time_range,
    )
    pairs = analytics.compute_correlation(
        alarms,
        lag_window_minutes=request.lag_window_minutes,
        severity_threshold=request.severity_threshold.value,
        min_support=request.min_support,
    )
    return AlarmCorrelationResponse(
        correlation_method=request.correlation_method.value,
        lag_window_minutes=request.lag_window_minutes,
        pairs=pairs,
        trace=_trace(),
    )


# --------------------------------------------------------------------------- #
# 08 — Flood analysis
# --------------------------------------------------------------------------- #


@router.post("/alarms/flood-analysis", response_model=FloodAnalysisResponse)
def flood_analysis(
    request: FloodAnalysisRequest, session: Session = Depends(get_session)
) -> FloodAnalysisResponse:
    alarms, _ = alarms_in_scope(
        session,
        asset_ids=request.asset_ids,
        unit=request.unit,
        site=request.site,
        time_range=request.time_range,
    )
    windows = analytics.compute_flood_windows(
        alarms,
        threshold_count=request.threshold_count,
        rolling_window_minutes=request.rolling_window_minutes,
    )
    return FloodAnalysisResponse(
        threshold_count=request.threshold_count,
        rolling_window_minutes=request.rolling_window_minutes,
        flood_windows=windows,
        trace=_trace(),
    )


# --------------------------------------------------------------------------- #
# 09 — Rationalization candidates
# --------------------------------------------------------------------------- #


@router.post("/alarms/rationalization-candidates", response_model=RationalizationResponse)
def rationalization_candidates(
    request: RationalizationRequest, session: Session = Depends(get_session)
) -> RationalizationResponse:
    alarms, assets = alarms_in_scope(
        session,
        asset_ids=request.asset_ids,
        unit=request.unit,
        site=request.site,
        time_range=request.time_range,
    )
    candidates = analytics.compute_rationalization(
        alarms,
        assets,
        recurrence_threshold=request.recurrence_threshold,
        stale_minutes_threshold=request.stale_minutes_threshold,
        now=datetime.now(UTC),
    )
    return RationalizationResponse(
        candidates=candidates,
        recurrence_threshold=request.recurrence_threshold,
        stale_minutes_threshold=request.stale_minutes_threshold,
        trace=_trace(),
    )


# --------------------------------------------------------------------------- #
# 10 — Priority score
# --------------------------------------------------------------------------- #


@router.post("/alarms/priority-score", response_model=PriorityScoreResponse)
def priority_score(
    request: PriorityScoreRequest, session: Session = Depends(get_session)
) -> PriorityScoreResponse:
    """Weighted priority for one alarm, with the factor breakdown.

    The breakdown is part of the contract, not a debugging aid: the copilot uses it
    to explain the ranking instead of inventing a rationale.
    """
    alarm = session.get(Alarm, request.alarm_id)
    if alarm is None:
        raise NotFoundError(f"No alarm with id {request.alarm_id}")
    asset = session.get(Asset, alarm.asset_id)
    if asset is None:  # pragma: no cover — foreign key guarantees this
        raise NotFoundError(f"No asset with id {alarm.asset_id}")

    history = alarm_history(session, alarm.asset_id, alarm.alarm_name)
    score, band, factors = analytics.compute_priority_score(alarm, asset, history)
    return PriorityScoreResponse(
        alarm_id=alarm.alarm_id,
        priority_score=score,
        band=band,
        factors=factors,
        trace=_trace(),
    )
