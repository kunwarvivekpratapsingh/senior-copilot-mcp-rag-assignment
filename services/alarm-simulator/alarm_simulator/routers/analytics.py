"""KPI reference data — endpoint 14."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..analytics import KPI_DEFINITIONS
from ..auth import require_bearer_token
from ..schemas import KpiDefinitionsResponse

router = APIRouter(tags=["analytics"], dependencies=[Depends(require_bearer_token)])


@router.get("/analytics/kpi-definitions", response_model=KpiDefinitionsResponse)
def kpi_definitions() -> KpiDefinitionsResponse:
    """Static reference data describing every KPI the summary endpoint can compute.

    Exposed as an endpoint rather than documentation alone so the copilot can
    explain a KPI's formula from the source system itself, rather than from a
    hard-coded string that would drift.
    """
    return KpiDefinitionsResponse(definitions=KPI_DEFINITIONS)
