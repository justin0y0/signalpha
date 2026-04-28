from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Earnings Movement Platform"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://earnings:earnings@postgres:5432/earnings"
    redis_url: str = "redis://redis:6379/0"

    alpha_vantage_api_key: str | None = None
    financial_modeling_prep_api_key: str | None = None
    polygon_api_key: str | None = None
    fred_api_key: str | None = None
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    sec_user_agent: str = "earnings-platform/1.0 your-email@example.com"

    model_dir: Path = Path("/app/artifacts")
    data_dir: Path = Path("/app/data")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])
    scheduler_timezone: str = "America/New_York"
    default_calendar_lookahead_days: int = 14
    prediction_confidence_warning_threshold: float = 0.70
    feature_completeness_warning_threshold: float = 0.80

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
