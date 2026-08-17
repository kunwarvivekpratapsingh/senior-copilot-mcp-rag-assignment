"""Configuration for the alarm-management MCP server.

The API token is read here and handed to the connector. It is never accepted as a
tool argument, so there is no path by which a language model driving this server can
read or leak it. That is the entire reason the MCP indirection exists.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    alarm_api_base_url: str = "http://localhost:8000"
    alarm_api_token: str = "demo-token"  # noqa: S105 — documented local placeholder
    alarm_api_timeout_seconds: float = 5.0
    alarm_api_max_retries: int = 2

    mcp_client_id: str = "copilot-mcp"
    mcp_alarm_host: str = "0.0.0.0"  # noqa: S104 — container-internal bind
    mcp_alarm_port: int = 9000

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
