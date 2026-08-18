import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from litestar.testing import AsyncTestClient
from procrastinate import PsycopgConnector
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from old_news import db, fetch
from old_news.api.app import create_app
from old_news.config import DatabaseSettings, Settings
from old_news.db.migrate import upgrade
from old_news.tasks import app as procrastinate_app

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "old-news-postgres:test"


def _build_postgres_image() -> None:
    exists = subprocess.run(["docker", "image", "inspect", POSTGRES_IMAGE], capture_output=True)
    if exists.returncode == 0:
        return
    subprocess.run(
        ["docker", "build", "-t", POSTGRES_IMAGE, "-f", "postgres.Dockerfile", "."],
        cwd=REPO_ROOT / "docker",
        check=True,
    )


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    _build_postgres_image()
    container = PostgresContainer(
        POSTGRES_IMAGE,
        username="old_news",
        password="old_news",
        dbname="old_news",
        driver=None,
    ).with_command("postgres -c shared_preload_libraries=pg_search")
    # The suite stays hermetic; the API path is exercised by compose, not here.
    container = container.with_env("PG_TUNING_OFFLINE", "1")
    with container as running:
        yield running


@pytest.fixture(scope="session")
def database_url(postgres: PostgresContainer) -> str:
    url = postgres.get_connection_url().replace("postgresql://", "postgres://", 1)
    # The suite once passed only because a developer's .env happened to name a
    # running database. Nothing here may touch anything but the container.
    assert str(postgres.get_exposed_port(5432)) in url
    return url


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(
        environment="test",
        database=DatabaseSettings(url=database_url),
        _env_file=None,
    )


@pytest.fixture(scope="session")
def queue_app(settings: Settings):
    """Procrastinate builds its connector from the environment at import time, so it
    must be pointed at the container explicitly — otherwise the suite quietly talks to
    whatever `OLD_NEWS_DATABASE__URL` happens to name."""
    connector = PsycopgConnector(conninfo=settings.database.psycopg_url)
    with procrastinate_app.replace_connector(connector):
        yield procrastinate_app


@pytest.fixture(scope="session")
def migrated(settings: Settings, queue_app) -> None:
    # Alembic runs its own event loop, so this fixture stays synchronous.
    upgrade(settings.database.sqlalchemy_url)


@pytest.fixture(scope="session", autouse=True)
async def queue_schema(migrated: None, queue_app) -> None:
    """Autouse: procrastinate migrates itself, and alembic can't do it from an
    async fixture because its env.py drives its own loop."""
    async with queue_app.open_async():
        await queue_app.schema_manager.apply_schema_async()


@pytest.fixture
async def database(migrated: None, settings: Settings) -> AsyncIterator[None]:
    """An engine for tests that talk to Postgres directly rather than through the app.

    Configures the shared HTTP client too, exactly as the worker entrypoint does —
    otherwise a test that runs a real worker fails the moment a job wants to fetch.
    """
    db.configure(settings.database)
    fetch.configure(settings.http)
    try:
        yield
    finally:
        await fetch.dispose()
        await db.dispose()


@pytest.fixture
async def clean(database: None) -> AsyncIterator[None]:
    """From the root down: hosts cascades to feeds, and feeds to everything else."""
    async with db.session() as session:
        await session.execute(text("TRUNCATE hosts CASCADE"))
    yield


@pytest.fixture
async def no_jobs(clean: None) -> AsyncIterator[None]:
    """`clean` truncates feeds; the queue is a separate schema procrastinate owns.

    Truncated afterwards as well: the database is session-scoped, so a test that
    claims a job without finishing it would leave it `doing` for everything after.
    """
    await _truncate("procrastinate_jobs CASCADE")
    yield
    await _truncate("procrastinate_jobs CASCADE")


@pytest.fixture
async def no_policies(database: None) -> AsyncIterator[None]:
    await _truncate("robots_policies")
    yield
    await _truncate("robots_policies")


async def _truncate(target: str) -> None:
    async with db.session() as session:
        await session.execute(text(f"TRUNCATE {target}"))


@pytest.fixture
async def client(migrated: None, settings: Settings) -> AsyncIterator[AsyncTestClient]:
    """The app builds its own engine, exactly as it does in production."""
    async with AsyncTestClient(app=create_app(settings)) as test_client:
        yield test_client
