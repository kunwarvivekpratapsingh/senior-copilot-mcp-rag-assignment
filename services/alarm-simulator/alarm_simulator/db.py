"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings, get_settings
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def build_engine(settings: Settings) -> Engine:
    """Create the engine for the configured database.

    In-memory SQLite needs ``StaticPool`` plus ``check_same_thread=False``: without
    them every connection gets its own private empty database, so the seeded data
    would be invisible to request handlers running on other threads.
    """
    if settings.alarm_sim_db_path == ":memory:":
        return create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(settings.database_url, connect_args={"check_same_thread": False})


def init_db(settings: Settings | None = None) -> Engine:
    """Create the schema and prepare the session factory. Idempotent."""
    global _engine, _SessionLocal
    settings = settings or get_settings()
    _engine = build_engine(settings)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised — call init_db() during startup")
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session scoped to one request."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised — call init_db() during startup")
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
