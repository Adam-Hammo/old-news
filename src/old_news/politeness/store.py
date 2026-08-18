"""Resolving the host a URL belongs to, as a foreign key.

A publisher is discovered from a feed URL, so somebody has to turn one into the
other. That happens here, once, and returns the id everything else references.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news.db import Host
from old_news.politeness.hosts import host_of


async def ensure(session: AsyncSession, name: str) -> uuid.UUID:
    """The host row for a name, created if new. Hosts are shared, so two feeds
    arriving at once both have to succeed."""
    await session.execute(insert(Host).values(name=name).on_conflict_do_nothing())
    return (await session.execute(select(Host.id).where(Host.name == name))).scalar_one()


async def resolve(session: AsyncSession, url: str) -> uuid.UUID | None:
    """The host a URL belongs to. None when it names none, and so can't be polled."""
    name = host_of(url)
    return await ensure(session, name) if name else None
