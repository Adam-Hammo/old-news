import datetime
import uuid

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey

# Bumped when anything changes *how* a page is asked for. Refusals are counted per
# policy, so a bump forgives what came before without deleting a row — `extractor_version`
# makes the same bargain. Refusing the old way of asking is not refusing the new one.
CAPTURE_POLICY = "2"


class PageCapture(UUIDPrimaryKey, Base):
    """The article page behind one version, as served."""

    __tablename__ = "page_captures"
    __table_args__ = (
        Index("ix_page_captures_version_fetched", "item_version_id", text("fetched_at DESC")),
        # What makes the 204 URLs arriving in more than one feed cost one fetch each.
        Index("ix_page_captures_url_body", "url", "body_hash"),
        Index(
            "ix_page_captures_succeeded",
            "item_version_id",
            postgresql_where=text("status BETWEEN 200 AND 299"),
        ),
    )

    item_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("item_versions.id", ondelete="CASCADE")
    )

    # The publisher this page came from, which is often not the one serving the feed.
    # A foreign key rather than a string derived again at read time: that is how
    # `feeds.host` used to drift, and one function must own how a host is worked out.
    host_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hosts.id"), index=True
    )

    url: Mapped[str] = mapped_column(Text)
    # After redirects. Kept separately because a publisher that moved is worth knowing
    # about, and because it is what the extractor must resolve relative links against.
    final_url: Mapped[str] = mapped_column(Text, server_default="")

    fetched_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)
    # 0 for a transport failure, which is not an HTTP status at all.
    status: Mapped[int] = mapped_column(Integer, server_default="0")

    body_hash: Mapped[bytes] = mapped_column(LargeBinary)
    body: Mapped[bytes] = mapped_column(LargeBinary, server_default=text("''::bytea"))
    dictionary_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("zstd_dictionaries.id"), nullable=True, index=True
    )

    headers: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error: Mapped[str] = mapped_column(Text, server_default="")

    # How the page was asked for. Refusals are counted per policy, so improving the way
    # we ask forgives every attempt made before it without deleting a row — the same
    # bargain `extractions.extractor_version` makes. A publisher that refused the old
    # way of asking has not refused the new one.
    capture_policy: Mapped[str] = mapped_column(String(16), server_default="1")

    @hybrid_property
    def succeeded(self) -> bool:
        """The fetch answered. A 403 is a fact worth keeping and not a page to read."""
        return 200 <= self.status < 300

    @succeeded.inplace.expression
    @classmethod
    def _succeeded_expression(cls):
        return cls.status.between(200, 299)

    def __str__(self) -> str:
        return f"{self.status} {self.url}"
