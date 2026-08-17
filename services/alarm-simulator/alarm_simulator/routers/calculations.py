"""Calculation code generation and execution — endpoints 12 and 13.

Modelled as two steps because the second is impossible without the identifier the
first returns. That makes this pair the cleanest demonstration of tool chaining in
the whole API surface, which is why the copilot features it.

The ``generated_code`` string is for display. Execution runs a real, reviewed
implementation selected by calculation type — the service never executes a string,
because a source system that evaluates arbitrary code on request is a vulnerability,
not a feature.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import analytics
from ..auth import require_bearer_token
from ..config import Settings, get_settings
from ..db import get_session
from ..errors import NotFoundError
from ..models import Calculation
from ..queries import alarms_in_scope
from ..schemas import (
    CalculationExecuteRequest,
    CalculationExecuteResponse,
    CalculationGenerateRequest,
    CalculationGenerateResponse,
    TimeRange,
    TraceEnvelope,
)
from ..trace import trace_context

router = APIRouter(tags=["calculations"], dependencies=[Depends(require_bearer_token)])


def _time_range_from_filters(filters: dict[str, Any]) -> TimeRange | None:
    """Filters carry start_time/end_time flat rather than nested, per the collections."""
    start, end = filters.get("start_time"), filters.get("end_time")
    if not (start and end):
        return None
    return TimeRange(start_time=start, end_time=end)


@router.post("/calculation-code/generate", response_model=CalculationGenerateResponse)
def generate_calculation(
    request: CalculationGenerateRequest, session: Session = Depends(get_session)
) -> CalculationGenerateResponse:
    """Register a calculation and return its identifier plus the code it represents."""
    calculation = Calculation(
        calculation_id=f"CALC-{uuid.uuid4().hex[:12]}",
        calculation_type=request.calculation_type.value,
        generated_code=analytics.CALCULATION_CODE[request.calculation_type.value],
        filters_json=json.dumps(request.filters, default=str),
        created_at=datetime.now(UTC),
    )
    session.add(calculation)
    session.commit()

    return CalculationGenerateResponse(
        calculation_id=calculation.calculation_id,
        calculation_type=calculation.calculation_type,
        generated_code=calculation.generated_code,
        filters=request.filters,
        created_at=calculation.created_at,
    )


@router.post("/calculation-code/execute", response_model=CalculationExecuteResponse)
def execute_calculation(
    request: CalculationExecuteRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CalculationExecuteResponse:
    """Run a previously generated calculation.

    Filters supplied here override those captured at generation time, so the same
    calculation can be re-run against a different scope without regenerating it.
    """
    calculation = session.get(Calculation, request.calculation_id)
    if calculation is None:
        raise NotFoundError(f"No calculation with id {request.calculation_id}")

    filters = {**json.loads(calculation.filters_json), **request.filters}
    time_range = _time_range_from_filters(filters)

    alarms, assets = alarms_in_scope(
        session,
        unit=filters.get("unit"),
        site=filters.get("site"),
        asset_ids=filters.get("asset_ids"),
        time_range=time_range,
    )

    days = settings.alarm_sim_days
    if time_range:
        days = max((time_range.end_time - time_range.start_time).days, 1)

    value, columns, rows, interpretation = analytics.execute_calculation(
        calculation.calculation_type, alarms, assets, days
    )

    return CalculationExecuteResponse(
        calculation_id=calculation.calculation_id,
        calculation_type=calculation.calculation_type,
        value=value,
        unit=analytics.CALCULATION_UNITS[calculation.calculation_type],
        columns=columns,
        rows=rows,
        interpretation=interpretation,
        trace=TraceEnvelope(**trace_context()),
    )
