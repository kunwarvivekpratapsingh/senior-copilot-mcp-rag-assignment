"""Backend configuration — LLD §9."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MCP servers the registry discovers at startup.
    mcp_alarm_url: str = "http://localhost:9000/mcp"
    mcp_github_url: str = "http://localhost:9001/mcp"
    mcp_tool_timeout_seconds: float = 8.0

    # 'anthropic' uses ANTHROPIC_API_KEY; 'rule_based' needs no credentials and runs
    # the same workflow deterministically.
    llm_provider: str = "rule_based"
    llm_model: str = "claude-opus-5"
    llm_effort: str = "high"
    anthropic_api_key: str = ""

    # Retrieval.
    chroma_path: str = ".chroma"
    chroma_collection: str = "operations-docs"
    document_path: str = "./rag/documents"
    embedding_model: str = "hashing"
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.35

    backend_port: int = 8080
    log_level: str = "INFO"
    log_format: str = "json"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_anthropic(self) -> bool:
        """Only use the API when a provider is chosen AND a key is present.

        Falling back rather than crashing matters: a demo that dies at startup because
        an optional key is missing is worse than one that runs deterministically.
        """
        return self.llm_provider.lower() == "anthropic" and bool(
            self.anthropic_api_key and self.anthropic_api_key != "replace-me"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
