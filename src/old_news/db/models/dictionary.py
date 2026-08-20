import datetime
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class ZstdDictionary(UUIDPrimaryKey, Base):
    """A trained compression dictionary, scoped to whatever produced the bytes."""

    __tablename__ = "zstd_dictionaries"
    __table_args__ = (
        CheckConstraint("(feed_id IS NULL) <> (host_id IS NULL)", name="one_scope"),
        UniqueConstraint("dict_id", "feed_id", "host_id", postgresql_nulls_not_distinct=True),
    )

    # zstd's own identifier, stamped into every frame, so a body finds its own dictionary.
    # No separate index: it leads the unique constraint above.
    dict_id: Mapped[int] = mapped_column(Integer)

    feed_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=True, index=True
    )
    host_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, index=True
    )

    body: Mapped[bytes] = mapped_column(LargeBinary)

    # What it was trained on, so a retrain can tell whether it has more to learn from.
    sample_count: Mapped[int] = mapped_column(Integer)
    sample_bytes: Mapped[int] = mapped_column(Integer)
    trained_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
