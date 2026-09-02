import datetime

from sqlalchemy import Boolean, Text, text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from old_news.db.base import NOW, Base, Timestamptz, UUIDPrimaryKey
from old_news.db.models.page import failure_run


class Host(UUIDPrimaryKey, Base):
    """A publisher. The aggregate root that feeds and robots rules hang off."""

    __tablename__ = "hosts"

    # Punycoded, lowercased, `www.` stripped — whatever `politeness.host_of` says. Not the
    # primary key, so re-deriving after a parser fix updates one row.
    name: Mapped[str] = mapped_column(Text, unique=True, index=True)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(Timestamptz, server_default=NOW)

    # Some publishers link articles at an apex that resolves nowhere. Learned from the one
    # capture that only worked with the prefix put back, so it costs one request per host.
    requires_www: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    @hybrid_property
    def capture_failures(self) -> int:
        """Read off the capture log rather than stored, so there is one copy of the number."""
        raise NotImplementedError("only queryable as SQL; select it rather than loading a row")

    @capture_failures.inplace.expression
    @classmethod
    def _capture_failures_expression(cls):
        return failure_run(cls.id).length

    @hybrid_property
    def last_capture_failure(self) -> datetime.datetime:
        """When the run counted by `capture_failures` last grew."""
        raise NotImplementedError("only queryable as SQL; select it rather than loading a row")

    @last_capture_failure.inplace.expression
    @classmethod
    def _last_capture_failure_expression(cls):
        return failure_run(cls.id).latest
