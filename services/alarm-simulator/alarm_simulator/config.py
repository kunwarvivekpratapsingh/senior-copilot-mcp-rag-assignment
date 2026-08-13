"""Simulator configuration.

Read once at startup into a typed settings object rather than scattered
``os.getenv`` calls, so every knob is discoverable in one place and mistyped
values fail fast at boot instead of at first request.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for the Alarm Management API simulator."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The bearer token every endpoint except /health requires. Matches the
    # `auth_token` collection variable in the supplied Postman collections.
    # The default is a documented placeholder for local development, not a secret:
    # deployments override it via ALARM_API_TOKEN.
    alarm_api_token: str = "demo-token"  # noqa: S105

    # SQLite location. ":memory:" keeps the database in-process, which is what the
    # test suite uses; the container mounts a volume path.
    alarm_sim_db_path: str = ":memory:"

    # Seeding the generator makes every asset_id and alarm_id reproducible, so the
    # demo, the tests, and the Postman collections all see identical data.
    alarm_sim_seed: int = 20260811

    # Size of the synthetic estate.
    alarm_sim_days: int = 120
    alarm_sim_alarm_count: int = 3000

    # Pagination guard: a caller asking for an unbounded page is clamped rather
    # than allowed to pull the whole table into memory.
    max_page_size: int = 500

    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        if self.alarm_sim_db_path == ":memory:":
            return "sqlite://"
        return f"sqlite:///{self.alarm_sim_db_path}"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so configuration is parsed exactly once per process."""
    return Settings()
