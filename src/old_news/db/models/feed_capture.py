import datetime
import uuid

from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey


class FeedCapture(UUIDPrimaryKey, Base):
    """One version's text as the feed served it, carved out of the stored document."""

    __tablename__ = "feed_captures"
    __table_args__ = (
        # With the hash rather than on its own: re-carving after a parser bump has to be
        # able to insert, and identical bytes have to conflict.
        UniqueConstraint("item_version_id", "body_hash"),
    )

    item_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("item_versions.id", ondelete="CASCADE")
    )
    # Which document these bytes were carved from, and the only way back to them.
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )

    body_hash: Mapped[bytes] = mapped_column(LargeBinary)
    body: Mapped[bytes] = mapped_column(LargeBinary, server_default=text("''::bytea"))
    dictionary_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("zstd_dictionaries.id"), nullable=True, index=True
    )

    # The provenance `item_versions` never had: which parse chose these bytes.
    parser_version: Mapped[str] = mapped_column(String(32))
    captured_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    def __str__(self) -> str:
        return f"{self.parser_version}: {len(self.body)} bytes"
