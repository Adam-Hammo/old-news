from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from old_news.config.admin import AdminSettings
from old_news.config.api import ApiSettings
from old_news.config.database import DatabaseSettings
from old_news.config.extract import ExtractSettings
from old_news.config.http import HttpSettings
from old_news.config.ingest import IngestSettings
from old_news.config.kindle import KindleSettings
from old_news.config.robots import RobotsSettings
from old_news.config.storage import StorageSettings
from old_news.config.telemetry import TelemetrySettings
from old_news.config.worker import WorkerSettings


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
    admin: AdminSettings = Field(default_factory=AdminSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    robots: RobotsSettings = Field(default_factory=RobotsSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    extract: ExtractSettings = Field(default_factory=ExtractSettings)
    kindle: KindleSettings = Field(default_factory=KindleSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "AdminSettings",
    "ApiSettings",
    "DatabaseSettings",
    "ExtractSettings",
    "HttpSettings",
    "IngestSettings",
    "KindleSettings",
    "RobotsSettings",
    "Settings",
    "StorageSettings",
    "TelemetrySettings",
    "WorkerSettings",
    "get_settings",
]
