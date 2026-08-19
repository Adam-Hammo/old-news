import datetime

from sqlalchemy import Boolean, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class Host(UUIDPrimaryKey, Base):
    """A publisher. The aggregate root that feeds and robots rules hang off.

    Not a cache of something derived from a feed URL — that is only how a host is
    discovered. It owns state no feed can produce: robots rules, crawl delay, and
    whatever else gets observed about a publisher later.
    """

    __tablename__ = "hosts"

    # Punycoded, lowercased, `www.` stripped — whatever `politeness.host_of` says.
    # A surrogate key rather than this: re-deriving after a parser fix is then an
    # update to one row instead of a cascading key change.
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    # Some publishers serve the feed from `www` and link their articles at the apex,
    # which then resolves nowhere.
    requires_www: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
