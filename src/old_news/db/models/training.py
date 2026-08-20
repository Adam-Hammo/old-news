import datetime
import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey, one_of


class Dimension(enum.StrEnum):
    """What a rule can match on. Each member needs matching code, so these are the built ones."""

    TITLE_PHRASE = "title_phrase"
    URL_PATTERN = "url_pattern"


class RuleSource(enum.StrEnum):
    """Where a rule came from, which decides whether it could ever be rebuilt."""

    # Ships with a migration.
    SEED = "seed"
    # Taste, and unrecoverable — which is why this table wants its own backup.
    HAND = "hand"
    # Derived from the corpus, and self-correcting.
    OBSERVED = "observed"


class TrainingRule(UUIDPrimaryKey, Base):
    """One trained opinion about what is worth keeping. Only the blocking tier is read yet."""

    __tablename__ = "training_rules"
    __table_args__ = (
        CheckConstraint(one_of("dimension", Dimension), name="known_dimension"),
        CheckConstraint(one_of("source", RuleSource), name="known_source"),
        # A global rule has a null feed, which Postgres would otherwise let repeat.
        UniqueConstraint("dimension", "pattern", "feed_id", postgresql_nulls_not_distinct=True),
    )

    # `Mapped[str]`, not `Mapped[Dimension]`: Postgres returns a string, which compares
    # equal to a StrEnum member but is not it.
    dimension: Mapped[str] = mapped_column(String(16))

    # A case-insensitive substring, not a regex: untrusted titles plus backtracking.
    pattern: Mapped[str] = mapped_column(Text)

    blocks: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # Null is global. A feed id makes it an override for that feed only.
    feed_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=True, index=True
    )

    source: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
