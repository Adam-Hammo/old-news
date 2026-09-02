import datetime
import hashlib
import subprocess
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any

import pytest
from litestar.testing import AsyncTestClient
from procrastinate import PsycopgConnector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.postgres import PostgresContainer

from old_news import db, fetch
from old_news.api.app import create_app
from old_news.config import DatabaseSettings, Settings
from old_news.db import Document, FeedCapture, FeedExtraction, Item, ItemVersion
from old_news.db import bytes as codec
from old_news.db.migrate import upgrade
from old_news.subscriptions.service import add, drop
from old_news.tasks import app as procrastinate_app

from factories import (
    DocumentFields,
    ExtractionFields,
    FeedCaptureFields,
    ItemFields,
    ItemVersionFields,
)

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
    """Procrastinate builds its connector from the environment at import, so point it here."""
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
    """An engine for tests that talk to Postgres directly, plus the shared HTTP client."""
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
    """`clean` truncates feeds; the queue is a separate schema, and session-scoped."""
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


@pytest.fixture
async def served(client: AsyncTestClient, clean: None) -> Callable[[], Awaitable[AsyncTestClient]]:
    """The app over an empty archive. Await it once the rows are built, then make requests.

    `AsyncTestClient` runs the app on an event loop of its own, and asyncpg binds a
    connection to the loop that opened it. So the pool a test filled writing its rows has to
    be emptied before the app reads them, or the request inherits a connection it cannot
    drive. Skipping the handover is a 500, not a silent pass.
    """

    async def handover() -> AsyncTestClient:
        await db.engine().dispose()
        return client

    return handover


# --- rows for the reading screens, built by hand: a poll is not what they are about ---


@pytest.fixture
def feed() -> Callable[..., Coroutine[Any, Any, uuid.UUID]]:
    """A subscribed feed, filed under a category unless told otherwise."""

    async def build(host: str, *, category: str = "", active: bool = True) -> uuid.UUID:
        made = await add(f"https://{host}/feed.xml", title=host, category=category)
        assert made is not None
        if not active:
            await drop(made.id)
        return made.id

    return build


@db.transactional
async def _story(
    session: AsyncSession,
    feed_id: uuid.UUID,
    *,
    title: str,
    body: str,
    first_seen_at: datetime.datetime | None,
    published_at: datetime.datetime | None,
    url: str,
) -> uuid.UUID:
    document = Document(feed_id=feed_id, **DocumentFields.kwargs())
    session.add(document)
    await session.flush()

    item = Item(feed_id=feed_id, **ItemFields.kwargs(guid=url, identity_key=url))
    if first_seen_at is not None:
        item.first_seen_at = first_seen_at
    session.add(item)
    await session.flush()

    version = ItemVersion(
        item_id=item.id,
        document_id=document.id,
        **ItemVersionFields.kwargs(
            title=title, url=url, canonical_url=url, published_at=published_at
        ),
    )
    session.add(version)
    await session.flush()

    if body:
        capture = FeedCapture(
            item_version_id=version.id,
            document_id=document.id,
            body=codec.compress(body.encode(), level=12),
            **FeedCaptureFields.kwargs(body_hash=hashlib.sha256(body.encode()).digest()),
        )
        session.add(capture)
        await session.flush()
        session.add(
            FeedExtraction(
                item_version_id=version.id,
                feed_capture_id=capture.id,
                **ExtractionFields.kwargs(body=body),
            )
        )
        await session.flush()

    return item.id


@pytest.fixture
def story() -> Callable[..., Coroutine[Any, Any, uuid.UUID]]:
    """One item with a head version, and a feed reading when given a body."""
    counter = iter(range(1_000))

    async def build(
        feed_id: uuid.UUID,
        title: str,
        *,
        body: str = "",
        first_seen_at: datetime.datetime | None = None,
        published_at: datetime.datetime | None = None,
    ) -> uuid.UUID:
        return await _story(
            feed_id,
            title=title,
            body=body,
            first_seen_at=first_seen_at,
            published_at=published_at,
            url=f"https://loopback.example.com/{next(counter)}",
        )

    return build
