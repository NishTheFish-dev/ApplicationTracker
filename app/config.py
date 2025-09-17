from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APPTRACKER_",
    )
    EXCEL_PATH: str = Field(
        default="Applications.xlsx",
        description="Path to the master Excel workbook used for storage",
    )
    DEBUG: bool = Field(default=False)
    REQUEST_TIMEOUT_SECONDS: int = Field(default=20)
    USER_AGENT: str = Field(default="ApplicationTracker/0.1 (+https://example.local)")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
