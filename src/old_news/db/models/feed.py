import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey

if TYPE_CHECKING:
    from old_news.db.models.subscription import Subscription


class Feed(UUIDPrimaryKey, Base):
    __tablename__ = "feeds"

    # Foreign keys are not indexed automatically, and every poll groups by host.
    host_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hosts.id"), index=True
    )
    url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    site_url: Mapped[str] = mapped_column(Text, server_default="")
    title: Mapped[str] = mapped_column(Text, server_default="")
    description: Mapped[str] = mapped_column(Text, server_default="")
    language: Mapped[str] = mapped_column(String(32), server_default="")
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    icon_url: Mapped[str] = mapped_column(Text, server_default="")

    # <generator> — the publishing software, not the masthead. Platform migrations
    # are what rewrite a feed's guids, so this is what you group by when they do.
    platform: Mapped[str] = mapped_column(Text, server_default="")
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hub_url: Mapped[str] = mapped_column(Text, server_default="")

    etag: Mapped[str] = mapped_column(Text, server_default="")
    last_modified: Mapped[str] = mapped_column(Text, server_default="")

    last_polled_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)
    last_success_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)
    next_poll_at: Mapped[datetime.datetime] = mapped_column(
        Timestamptz, server_default=NOW, index=True
    )

    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str] = mapped_column(Text, server_default="")
    # The poller giving up, not a choice. Unsubscribing is Subscription.active.
    suspended: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), index=True)
    suspended_reason: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    subscription: Mapped[Subscription | None] = relationship(
        lazy="raise", back_populates="feed", cascade="all, delete-orphan", uselist=False
    )

    def __str__(self) -> str:
        return self.title or self.url
