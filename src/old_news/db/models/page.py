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

# Bumped when anything changes *how* a page is asked for. Refusals count per policy, so a
# bump forgives what came before without deleting a row.
CAPTURE_POLICY = "2"


class CaptureOutcome(enum.StrEnum):
    """What one visit to a page turned out to be. Only `FAILED` counts against a publisher."""

    OK = "ok"
    # 404 or 410 — about this URL, so it must not close a host that answers everything else.
    GONE = "gone"
    FAILED = "failed"
    # The three we never sent.
    DISALLOWED = "disallowed"
    REFUSED = "refused"
    UNKNOWN_RULES = "unknown_rules"


class PageCapture(UUIDPrimaryKey, Base):
    """One visit to the article page behind one version, as served. Append-only.

    Both the artefact and the log of asking for it, so every decision that spends a slot
    in the capture batch writes one — including the decisions not to fetch.
    """

    __tablename__ = "page_captures"
    __table_args__ = (
        CheckConstraint(one_of("outcome", CaptureOutcome), name="known_capture_outcome"),
        Index("ix_page_captures_version_fetched", "item_version_id", text("fetched_at DESC")),
        # What makes the 204 URLs arriving in more than one feed cost one fetch each.
        Index("ix_page_captures_url_body", "url", "body_hash"),
        # Partial, so it must spell success the way `succeeded` does or Postgres stops
        # using it — the predicate has to imply the index's.
        Index(
            "ix_page_captures_succeeded",
            "item_version_id",
            postgresql_where=text("outcome = 'ok'"),
        ),
        # Counting a host's failures back to its last success reads this, newest first.
        # Both equalities lead, or the policy is a recheck on every row read.
        Index(
            "ix_page_captures_host_fetched",
            "host_id",
            "capture_policy",
            text("fetched_at DESC"),
            "outcome",
        ),
    )

    item_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("item_versions.id", ondelete="CASCADE")
    )

    # Often not the host serving the feed. A key rather than a string re-derived per
    # read, so one function owns how a host is worked out.
    host_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hosts.id"), index=True
    )

    url: Mapped[str] = mapped_column(Text)
    # After redirects, which is what the extractor resolves relative links against.
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

    capture_policy: Mapped[str] = mapped_column(String(16), server_default="1")

    @hybrid_property
    def succeeded(self) -> bool:
        """The fetch answered with a body worth reading."""
        return self.outcome == CaptureOutcome.OK

    @succeeded.inplace.expression
    @classmethod
    def _succeeded_expression(cls):
        return cls.outcome == CaptureOutcome.OK

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
