from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from old_news import observability
from old_news.config import DatabaseSettings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure(settings: DatabaseSettings) -> AsyncEngine:
    """Build the engine. Called once per process, from a lifespan or a CLI entrypoint.

    asyncpg binds a connection to the loop that opened it, so the engine must be
    created on the loop that will use it — never at import time.
    """
    global _engine, _sessionmaker

    _engine = create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.pool_max_size,
        pool_pre_ping=True,
        echo=settings.log_queries,
    )
    # expire_on_commit would re-fetch every attribute after a commit, which turns
    # a returned object into a lazy-load minefield once the session is closed.
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)

    # The engine has to be handed over rather than discovered: instrumentation
    # patches sqlalchemy's factory, and the name imported above is not it.
    observability.instrument_engine(_engine)
    return _engine


async def dispose() -> None:
    global _engine, _sessionmaker

    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("database engine not configured; call db.configure() first")
    return _engine


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """A session and a transaction. Commits on success, rolls back on anything else."""
    if _sessionmaker is None:
        raise RuntimeError("database engine not configured; call db.configure() first")

    async with _sessionmaker() as current, current.begin():
        yield current
