import pytest
from sqlalchemy.engine import make_url

from old_news.config import AdminSettings, DatabaseSettings, Settings


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
    assert settings.database.url.get_secret_value() == "postgres://u:p@host:6000/db"


def test_sqlalchemy_url_names_the_driver():
    settings = DatabaseSettings(url="postgres://u:p@h:5432/d")

    assert settings.sqlalchemy_url == "postgresql+asyncpg://u:p@h:5432/d"


def test_credentials_survive_percent_encoding():
    """A password containing @ splits the DSN in the wrong place if mishandled."""
    settings = DatabaseSettings(url="postgres://someone:se%40cret@db.internal:6543/archive")

    url = make_url(settings.sqlalchemy_url)
    assert (url.username, url.password) == ("someone", "se@cret")
    assert (url.host, url.port, url.database) == ("db.internal", 6543, "archive")


def test_psycopg_url_scheme():
    settings = DatabaseSettings(url="postgres://u:p@h:5432/d")

    assert settings.psycopg_url == "postgresql://u:p@h:5432/d"


def test_credentials_never_appear_in_a_repr():
    """Tracebacks, pytest failure dumps and log lines all go through repr."""
    settings = Settings(
        database=DatabaseSettings(url="postgres://u:dbsecret1@host:5432/db"),
        admin=AdminSettings(password_hash="adminsecret2", session_secret="sessionsecret3"),
        _env_file=None,
    )

    rendered = repr(settings)

    assert "dbsecret1" not in rendered
    assert "adminsecret2" not in rendered
    assert "sessionsecret3" not in rendered


def test_robots_matches_the_agent_we_actually_send():
    """One name, not two. A second copy of the product token would silently keep
    matching an agent we no longer identify as."""
    settings = Settings(_env_file=None)

    assert settings.http.user_agent.split("/")[0] == "old-news"
    assert not hasattr(settings.robots, "user_agent")
