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
    USER_AGENT: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        description="User-Agent sent when fetching pages; override via APPTRACKER_USER_AGENT",
    )
    FETCH_PROXY_READER: str = Field(
        default="",
        description=(
            "Optional proxy reader base URL to bypass strict bot blocks (e.g., 'https://r.jina.ai'). "
            "When set, the fetcher will retry via this reader on 403 responses."
        ),
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
