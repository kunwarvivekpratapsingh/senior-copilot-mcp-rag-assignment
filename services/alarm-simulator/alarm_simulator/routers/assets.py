"""Asset search and metadata — endpoints 01 and 02."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_bearer_token
from ..db import get_session
from ..errors import NotFoundError
from ..models import Alarm, Asset
from ..schemas import AssetMetadataResponse, AssetSearchResponse, AssetSummary

router = APIRouter(tags=["assets"], dependencies=[Depends(require_bearer_token)])


@router.get("/assets/search", response_model=AssetSearchResponse)
def search_assets(
    query: str = Query(..., min_length=1, description="Free-text match on asset name or type"),
    limit: int = Query(10, ge=1, le=100),
    unit: str | None = Query(None, description="Restrict to one unit"),
    session: Session = Depends(get_session),
) -> AssetSearchResponse:
    """Resolve a free-text asset name to structured asset records.

    Case-insensitive substring match across name and type, so both
    ``Boiler Feed Pump 101`` and ``compressor`` work. The ``unit`` filter appears
    only in the chaining collection but applies to every caller.
    """
    pattern = f"%{query.lower()}%"
    stmt = select(Asset).where(
        or_(
            func.lower(Asset.asset_name).like(pattern),
            func.lower(Asset.asset_type).like(pattern),
        )
    )
    if unit:
        stmt = stmt.where(Asset.unit == unit)
    stmt = stmt.order_by(Asset.asset_name).limit(limit)

    assets = list(session.execute(stmt).scalars().all())
    return AssetSearchResponse(
        query=query,
        count=len(assets),
        results=[
            AssetSummary(
                asset_id=a.asset_id,
                asset_name=a.asset_name,
                asset_type=a.asset_type,
                unit=a.unit,
                site=a.site,
                criticality=a.criticality,
            )
            for a in assets
        ],
    )


@router.get("/assets/{asset_id}/metadata", response_model=AssetMetadataResponse)
def get_asset_metadata(
    asset_id: str, session: Session = Depends(get_session)
) -> AssetMetadataResponse:
    """Full attributes for one asset, plus its current alarm counts."""
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError(f"No asset with id {asset_id}")

    total = session.scalar(
        select(func.count()).select_from(Alarm).where(Alarm.asset_id == asset_id)
    )
    active = session.scalar(
        select(func.count())
        .select_from(Alarm)
        .where(Alarm.asset_id == asset_id, Alarm.status == "active")
    )

    return AssetMetadataResponse(
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
        total_alarms=total or 0,
        active_alarms=active or 0,
    )
