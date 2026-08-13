from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from old_news.config.api import ApiSettings
from old_news.config.database import DatabaseSettings
from old_news.config.http import HttpSettings
from old_news.config.telemetry import TelemetrySettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OLD_NEWS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    api: ApiSettings = Field(default_factory=ApiSettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "ApiSettings",
    "DatabaseSettings",
    "HttpSettings",
    "Settings",
    "TelemetrySettings",
    "get_settings",
]
