"""Resolving the host a URL belongs to, as a foreign key. The one place that does it."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news.db import Host
from old_news.politeness.hosts import host_of


async def ensure(session: AsyncSession, name: str) -> uuid.UUID:
    """The host row for a name, created if new. Two feeds arriving at once both succeed."""
    found = await _id_of(session, name)
    if found is not None:
        return found
    await session.execute(insert(Host).values(name=name).on_conflict_do_nothing())
    return (await _id_of(session, name)) or _unreachable(name)


async def _id_of(session: AsyncSession, name: str) -> uuid.UUID | None:
    return (await session.execute(select(Host.id).where(Host.name == name))).scalar_one_or_none()


def _unreachable(name: str) -> uuid.UUID:
    raise LookupError(f"host {name} vanished between insert and read")


async def resolve(session: AsyncSession, url: str) -> uuid.UUID | None:
    """The host a URL belongs to. None when it names none, and so can't be polled."""
    name = host_of(url)
    return await ensure(session, name) if name else None
