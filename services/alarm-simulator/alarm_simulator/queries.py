"""Shared query construction.

Every filter the API supports is expressed once here rather than repeated across
routers, so a filter added to one endpoint behaves identically on the others.

All filtering goes through SQLAlchemy expression objects with bound parameters.
No SQL string is ever assembled by hand.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .models import Alarm, Asset
from .schemas import TimeRange


def assets_matching(
    session: Session,
    *,
    asset_ids: list[str] | None = None,
    unit: str | None = None,
    site: str | None = None,
) -> list[Asset]:
    """Resolve the asset scope for an analytical request."""
    stmt: Select[tuple[Asset]] = select(Asset)
    if asset_ids:
        stmt = stmt.where(Asset.asset_id.in_(asset_ids))
    if unit:
        stmt = stmt.where(Asset.unit == unit)
    if site:
        stmt = stmt.where(Asset.site == site)
    return list(session.execute(stmt).scalars().all())


def alarms_in_scope(
    session: Session,
    *,
    asset_ids: list[str] | None = None,
    unit: str | None = None,
    site: str | None = None,
    time_range: TimeRange | None = None,
    severities: list[str] | None = None,
    alarm_types: list[str] | None = None,
    statuses: list[str] | None = None,
) -> tuple[list[Alarm], list[Asset]]:
    """Fetch alarms and the assets they belong to for one analytical request.

    Returns both because nearly every analytics function needs asset attributes
    (name for grouping, criticality for scoring) and fetching them separately would
    mean a second round trip per call.
    """
    scoped_assets = assets_matching(session, asset_ids=asset_ids, unit=unit, site=site)
    scoped_ids = [a.asset_id for a in scoped_assets]

    stmt: Select[tuple[Alarm]] = select(Alarm)
    # An explicit scope that matched nothing must return nothing, rather than
    # silently widening to the whole estate.
    if asset_ids or unit or site:
        if not scoped_ids:
            return [], []
        stmt = stmt.where(Alarm.asset_id.in_(scoped_ids))

    if time_range:
        stmt = stmt.where(Alarm.start_time >= time_range.start_time)
        stmt = stmt.where(Alarm.start_time < time_range.end_time)
    if severities:
        stmt = stmt.where(Alarm.severity.in_(severities))
    if alarm_types:
        stmt = stmt.where(Alarm.alarm_type.in_(alarm_types))
    if statuses:
        stmt = stmt.where(Alarm.status.in_(statuses))

    alarms = list(session.execute(stmt).scalars().all())

    if not (asset_ids or unit or site):
        scoped_assets = list(session.execute(select(Asset)).scalars().all())
    return alarms, scoped_assets


def alarm_history(session: Session, asset_id: str, alarm_name: str) -> list[Alarm]:
    """Every occurrence of one alarm name on one asset, oldest first."""
    stmt = (
        select(Alarm)
        .where(Alarm.asset_id == asset_id, Alarm.alarm_name == alarm_name)
        .order_by(Alarm.start_time)
    )
    return list(session.execute(stmt).scalars().all())


def related_alarms(
    session: Session, asset_id: str, around: datetime, window_minutes: int = 60
) -> list[Alarm]:
    """Alarms on the same asset close in time to a reference alarm."""
    from datetime import timedelta

    stmt = (
        select(Alarm)
        .where(
            Alarm.asset_id == asset_id,
            Alarm.start_time >= around - timedelta(minutes=window_minutes),
            Alarm.start_time <= around + timedelta(minutes=window_minutes),
        )
        .order_by(Alarm.start_time)
    )
    return list(session.execute(stmt).scalars().all())
