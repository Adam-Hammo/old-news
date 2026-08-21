import datetime
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class Document(UUIDPrimaryKey, Base):
    """A feed document as served, kept whenever it differs from the previous one."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_feed_fetched", "feed_id", text("fetched_at DESC")),)

    feed_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("feeds.id", ondelete="CASCADE")
    )
    # After redirects, so a re-parse resolves relative entry links the way the parse at
    # ingest did. Without it a moved feed re-reads to different identities.
    final_url: Mapped[str] = mapped_column(Text, server_default="")

    fetched_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
    status: Mapped[int] = mapped_column(Integer)
    body_hash: Mapped[bytes] = mapped_column(LargeBinary)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    dictionary_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("zstd_dictionaries.id"), nullable=True, index=True
    )

    # Whether the parser of the day coped. Re-parsing later may disagree.
    parse_ok: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    parse_note: Mapped[str] = mapped_column(Text, server_default="")
