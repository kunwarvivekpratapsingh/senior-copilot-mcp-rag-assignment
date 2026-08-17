"""Alarm Management API simulator — application entry point.

The source system the copilot integrates with. Built to the specification in the
three Postman collections under ``postman/``; ``make contract`` runs them against a
live instance and is the acceptance gate for this service.

Run standalone::

    uvicorn alarm_simulator.main:app --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_engine, init_db
from .errors import register_error_handlers
from .models import Alarm, Asset
from .routers import alarms, analytics, assets, calculations, recommendations
from .schemas import HealthResponse
from .seed import seed_database
from .trace import TraceMiddleware

VERSION = "1.0.0"

logger = logging.getLogger("alarm_simulator")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create the schema and seed synthetic data before serving traffic."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    engine = init_db(settings)
    with Session(engine) as session:
        seed_database(session, settings)
        asset_count = session.scalar(select(func.count()).select_from(Asset)) or 0
        alarm_count = session.scalar(select(func.count()).select_from(Alarm)) or 0
    logger.info(
        "alarm simulator ready", extra={"assets": asset_count, "alarms": alarm_count}
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alarm Management API",
        description=(
            "Alarm Management API simulator for the Multi-MCP Enterprise Operations "
            "Copilot. Conforms to the Postman collections that specify it."
        ),
        version=VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(TraceMiddleware)
    register_error_handlers(app)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        """Unauthenticated liveness probe.

        Deliberately outside the bearer-token dependency so container health checks
        and the collections' first request work without credentials.
        """
        with Session(get_engine()) as session:
            asset_count = session.scalar(select(func.count()).select_from(Asset)) or 0
            alarm_count = session.scalar(select(func.count()).select_from(Alarm)) or 0
        return HealthResponse(
            version=VERSION, asset_count=asset_count, alarm_count=alarm_count
        )

    app.include_router(assets.router)
    app.include_router(alarms.router)
    app.include_router(recommendations.router)
    app.include_router(calculations.router)
    app.include_router(analytics.router)
    return app


app = create_app()
