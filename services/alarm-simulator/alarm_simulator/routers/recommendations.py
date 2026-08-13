"""Operator recommendations — endpoint 11."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import analytics
from ..auth import require_bearer_token
from ..db import get_session
from ..errors import NotFoundError
from ..models import Alarm, Asset
from ..queries import alarm_history, related_alarms
from ..routers.alarms import _record
from ..schemas import (
    AssetMetadataResponse,
    OperatorActionsRequest,
    OperatorActionsResponse,
    TraceEnvelope,
)
from ..trace import trace_context

router = APIRouter(tags=["recommendations"], dependencies=[Depends(require_bearer_token)])


@router.post("/recommendations/operator-actions", response_model=OperatorActionsResponse)
def operator_actions(
    request: OperatorActionsRequest, session: Session = Depends(get_session)
) -> OperatorActionsResponse:
    """Ordered actions for an operator responding to one alarm.

    The three ``include_*`` flags are opt-in because each costs an extra query, and
    a caller that only needs the action list should not pay for context it will
    discard. The copilot enables all three for the acceptance scenario.
    """
    alarm = session.get(Alarm, request.alarm_id)
    if alarm is None:
        raise NotFoundError(f"No alarm with id {request.alarm_id}")

    asset = session.get(Asset, alarm.asset_id)
    if asset is None:  # pragma: no cover — foreign key guarantees this
        raise NotFoundError(f"No asset with id {alarm.asset_id}")

    response = OperatorActionsResponse(
        alarm_id=alarm.alarm_id,
        alarm_name=alarm.alarm_name,
        severity=alarm.severity,
        actions=analytics.build_recommendations(alarm),
        trace=TraceEnvelope(**trace_context()),
    )

    if request.include_related:
        neighbours = [
            a for a in related_alarms(session, alarm.asset_id, alarm.start_time)
            if a.alarm_id != alarm.alarm_id
        ]
        response.related_alarms = [_record(a, {alarm.asset_id: asset.asset_name}) for a in neighbours]

    if request.include_asset_context:
        response.asset_context = AssetMetadataResponse(
            asset_id=asset.asset_id,
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            unit=asset.unit,
            site=asset.site,
            criticality=asset.criticality,
            manufacturer=asset.manufacturer,
            model=asset.model,
            install_date=asset.install_date,
            last_maintenance=asset.last_maintenance,
            total_alarms=len(alarm_history(session, asset.asset_id, alarm.alarm_name)),
            active_alarms=sum(
                1
                for a in alarm_history(session, asset.asset_id, alarm.alarm_name)
                if a.status == "active"
            ),
        )

    if request.include_historical_pattern:
        response.historical_pattern = analytics.compute_historical_pattern(
            alarm_history(session, alarm.asset_id, alarm.alarm_name), datetime.now(UTC)
        )

    return response
