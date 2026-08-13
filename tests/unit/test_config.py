import pytest

from old_news.config import DatabaseSettings, Settings


def test_defaults_need_no_environment():
    settings = Settings()

    assert settings.environment == "local"
    assert settings.api.port == 8000
    assert settings.telemetry.enabled is False


def test_nested_env_vars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLD_NEWS_API__PORT", "9001")
    monkeypatch.setenv("OLD_NEWS_TELEMETRY__ENABLED", "true")
    monkeypatch.setenv("OLD_NEWS_DATABASE__URL", "postgres://u:p@host:6000/db")

    settings = Settings(_env_file=None)

    assert settings.api.port == 9001
    assert settings.telemetry.enabled is True
    assert settings.database.url == "postgres://u:p@host:6000/db"


def test_dsn_splits_for_asyncpg():
    settings = DatabaseSettings(url="postgres://someone:se%40cret@db.internal:6543/archive")

    assert settings.asyncpg_kwargs() == {
        "database": "archive",
        "user": "someone",
        "password": "se@cret",
        "host": "db.internal",
        "port": 6543,
    }


def test_psycopg_url_scheme():
    settings = DatabaseSettings(url="postgres://u:p@h:5432/d")

    assert settings.psycopg_url == "postgresql://u:p@h:5432/d"
