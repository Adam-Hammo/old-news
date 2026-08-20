import datetime
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Run, Timestamptz, UUIDPrimaryKey, one_of, run_of

# Bumped when anything changes *how* a page is asked for. Refusals are counted per
# policy, so a bump forgives what came before without deleting a row — `extractor_version`
# makes the same bargain. Refusing the old way of asking is not refusing the new one.
CAPTURE_POLICY = "2"


class CaptureOutcome(enum.StrEnum):
    """What one visit to a page turned out to be.

    Only `FAILED` counts against a publisher and only `OK` clears the count. The rest
    are stepped over: a dead link is about a URL, and the three we never sent are
    about us. That is what lets every decision record a row without the row changing
    what the next decision sees.
    """

    OK = "ok"
    # 404 or 410. About this URL, not the publisher: a few dead links must not close
    # a healthy host.
    GONE = "gone"
    FAILED = "failed"
    # robots.txt forbids the path, so nothing was sent.
    DISALLOWED = "disallowed"
    # The host is refusing everyone and its probe is not due. Nothing was sent.
    REFUSED = "refused"
    # The host's robots.txt has never been read, so there is no permission to rely on.
    UNKNOWN_RULES = "unknown_rules"


class PageCapture(UUIDPrimaryKey, Base):
    """One visit to the article page behind one version, as served. Append-only.

    Both the artefact and the log of asking for it. Every decision that spends a slot
    in the capture batch writes one of these, including the decisions not to fetch —
    a sweep that infers what it has tried from these rows cannot be told the truth by
    a path that stays silent.
    """

    __tablename__ = "page_captures"
    __table_args__ = (
        CheckConstraint(one_of("outcome", CaptureOutcome), name="known_capture_outcome"),
        Index("ix_page_captures_version_fetched", "item_version_id", text("fetched_at DESC")),
        # What makes the 204 URLs arriving in more than one feed cost one fetch each.
        Index("ix_page_captures_url_body", "url", "body_hash"),
        Index(
            "ix_page_captures_succeeded",
            "item_version_id",
            postgresql_where=text("status BETWEEN 200 AND 299"),
        ),
        # Counting a host's failures back to its last success reads this, newest first.
        Index("ix_page_captures_host_fetched", "host_id", text("fetched_at DESC"), "outcome"),
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
    # 0 for a transport failure, and for the visits that never left the process.
    status: Mapped[int] = mapped_column(Integer, server_default="0")

    outcome: Mapped[str] = mapped_column(Text)

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
        return f"{self.outcome} {self.status} {self.url}"


def _failures(host_id) -> Run:
    return run_of(
        PageCapture,
        at=lambda capture: capture.fetched_at,
        scope=lambda capture: (
            (capture.host_id == host_id) & (capture.capture_policy == CAPTURE_POLICY)
        ),
        counts=lambda capture: capture.outcome == CaptureOutcome.FAILED,
        # Only an answer clears the count. A dead link and the visits we declined to
        # send say nothing either way, which is what lets us record them.
        resets=lambda capture: capture.outcome == CaptureOutcome.OK,
    )


def host_failures(host_id) -> ColumnElement[int]:
    """Failed captures on this host since its last success, under the policy we ask by."""
    return _failures(host_id).length


def host_last_failure(host_id) -> ColumnElement[datetime.datetime]:
    """When that run last grew, or NULL if it is empty."""
    return _failures(host_id).latest
