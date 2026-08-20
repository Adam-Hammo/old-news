import functools
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Concatenate

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

# Whether this task already holds a transaction. A ContextVar rather than a global:
# concurrent jobs run on one loop and must not see each other's.
_open: ContextVar[bool] = ContextVar("old_news_transaction_open", default=False)


def configure(settings: DatabaseSettings) -> AsyncEngine:
    """Build the engine, once per process.

    asyncpg binds a connection to the loop that opened it, so never at import time.
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
async def session() -> AsyncGenerator[AsyncSession]:
    """A session and a transaction. Commits on success, rolls back on anything else."""
    if _sessionmaker is None:
        raise RuntimeError("database engine not configured; call db.configure() first")
    if _open.get():
        raise RuntimeError(
            "a transaction is already open on this task; pass the session down "
            "rather than opening a second one"
        )

    token = _open.set(True)
    try:
        async with _sessionmaker() as current, current.begin():
            yield current
    finally:
        _open.reset(token)


def transactional[**P, R](
    fn: Callable[Concatenate[AsyncSession, P], Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Make a function exactly one transaction, taking the session as its first argument."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        async with session() as current:
            return await fn(current, *args, **kwargs)

    return wrapper
