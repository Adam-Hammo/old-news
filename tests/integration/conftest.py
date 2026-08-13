import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from litestar.testing import AsyncTestClient
from piccolo.apps.migrations.commands.forwards import run_forwards
from procrastinate import PsycopgConnector
from testcontainers.community.postgres import PostgresContainer

from old_news.api.app import create_app
from old_news.config import DatabaseSettings, Settings
from old_news.db import DB
from old_news.tasks import app as queue_app

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
    return postgres.get_connection_url().replace("postgresql://", "postgres://", 1)


@pytest.fixture(scope="session")
async def migrated(database_url: str) -> AsyncIterator[None]:
    """Points the engine at the container and migrates it, leaving no pool behind.

    asyncpg binds a pool to the loop that created it, and AsyncTestClient runs
    handlers on a loop of its own — so a pool opened here would be unusable from
    inside a request. Whoever needs one opens it on their own loop.
    """
    DB.config.update(DatabaseSettings(url=database_url).asyncpg_kwargs())

    await DB.start_connection_pool()
    try:
        await run_forwards("all")
    finally:
        await DB.close_connection_pool()

    # Procrastinate migrates its own schema, separately from Piccolo.
    connector = PsycopgConnector(conninfo=DatabaseSettings(url=database_url).psycopg_url)
    with queue_app.replace_connector(connector) as live:
        async with live.open_async():
            await live.schema_manager.apply_schema_async()

    yield


@pytest.fixture
async def database(migrated: None) -> AsyncIterator[None]:
    await DB.start_connection_pool()
    try:
        yield
    finally:
        await DB.close_connection_pool()


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", _env_file=None)


@pytest.fixture
async def client(migrated: None, settings: Settings) -> AsyncIterator[AsyncTestClient]:
    """The app opens its own pool in lifespan, exactly as it does in production."""
    async with AsyncTestClient(app=create_app(settings)) as test_client:
        yield test_client
