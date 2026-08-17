"""Configuration for the GitHub Issues MCP server."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Mock is the default so the system demos with no credentials and no network.
    github_mock: bool = True
    github_token: str = "replace-me"  # noqa: S105 ? placeholder; real value via env
    github_repo: str = "owner/repo"

    mcp_github_host: str = "0.0.0.0"  # noqa: S104 ? container-internal bind
    mcp_github_port: int = 9001

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
