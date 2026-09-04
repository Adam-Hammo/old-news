import datetime
import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class Issue(UUIDPrimaryKey, Base):
    """One built periodical, and the bytes it was sent as."""

    __tablename__ = "issues"

    built_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    title: Mapped[str] = mapped_column(Text, server_default="")
    subject: Mapped[str] = mapped_column(Text, server_default="")

    # Send to Kindle's E999 carries no detail, so the only way to tell a broken book
    # from a bad night at Amazon is to post the same bytes again.
    body: Mapped[bytes] = mapped_column(LargeBinary, server_default=text("''::bytea"))
    byte_size: Mapped[int] = mapped_column(Integer, server_default="0")

    sent_at: Mapped[datetime.datetime | None] = mapped_column(Timestamptz, nullable=True)
    error: Mapped[str] = mapped_column(Text, server_default="")

    articles: Mapped[list[IssueItem]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", lazy="raise"
    )

    def __str__(self) -> str:
        return self.title or str(self.built_at)


class IssueItem(UUIDPrimaryKey, Base):
    """One article in one issue, which is what stops it going out twice."""

    __tablename__ = "issue_items"
    # The sweep asks whether an item has ever gone out, which the constraint below
    # cannot answer: it leads on the issue.
    __table_args__ = (UniqueConstraint("issue_id", "item_id"),)

    issue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("issues.id", ondelete="CASCADE")
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(Text, server_default="")
    position: Mapped[int] = mapped_column(Integer, server_default="0")

    issue: Mapped[Issue] = relationship(back_populates="articles", lazy="raise")
