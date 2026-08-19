import datetime
import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey, one_of


class Dimension(enum.StrEnum):
    """What a rule can match on.

    Each needs matching code, so this is what is implemented rather than what is planned:
    the check constraint follows the members, and adding one is a branch and a migration
    together.
    """

    TITLE_PHRASE = "title_phrase"
    URL_PATTERN = "url_pattern"


class RuleSource(enum.StrEnum):
    """Where a rule came from, which decides whether it could ever be rebuilt."""

    # Ships with a migration.
    SEED = "seed"
    # Taste. Unrecoverable, and the reason this table wants backing up on its own.
    HAND = "hand"
    # Derived from the corpus, and self-correcting.
    OBSERVED = "observed"


class TrainingRule(UUIDPrimaryKey, Base):
    """One trained opinion about what is worth keeping.

    Filtering only needs the blocking tier, so that is all this phase reads. Thumbs and
    scoring land in the same table later: the dimensions and the global/per-feed scope are
    the parts that would be expensive to change once rules exist.
    """

    __tablename__ = "training_rules"
    __table_args__ = (
        CheckConstraint(one_of("dimension", Dimension), name="known_dimension"),
        CheckConstraint(one_of("source", RuleSource), name="known_source"),
        # A global rule has a null feed, and Postgres would otherwise let the same global
        # rule be inserted any number of times.
        UniqueConstraint("dimension", "pattern", "feed_id", postgresql_nulls_not_distinct=True),
    )

    # `Mapped[str]`, not `Mapped[Dimension]`: what comes back out of Postgres is a string.
    # A StrEnum member compares equal to its own value, so `row.dimension is Dimension.X`
    # would be false but `==` is true, and that is the comparison anything here makes.
    dimension: Mapped[str] = mapped_column(String(16))

    # Matched as a case-insensitive substring, not a regex: every rule the corpus actually
    # justifies is a substring, and a regex over untrusted titles is a backtracking hazard
    # for nothing.
    pattern: Mapped[str] = mapped_column(Text)

    # The "never show me this" tier, which beats everything. Separate from the trained
    # strength that arrives with thumbs, because it is a different kind of statement.
    blocks: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    # Null is global. A feed id makes it an override for that feed only.
    feed_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE"), nullable=True, index=True
    )

    source: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
