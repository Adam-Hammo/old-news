import datetime

from sqlalchemy import Text
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
    # which then resolves nowhere. Set from the one capture that only worked with the
    # prefix put back; null means no reason to think otherwise.
    #
    # A timestamp rather than a flag because it is also the line before which refusals
    # stop counting: an attempt made while we were asking the wrong name is a fact about
    # our own mistake, not about the publisher. Written once and never moved — moving it
    # would zero the count again and retry forever.
    www_learned_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)
