"""Derived facts as views, compiled from the expressions that define them. Facts only."""

from typing import Any

from alembic_utils.pg_view import PGView
from alembic_utils.replaceable_entity import ReplaceableEntity, register_entities
from sqlalchemy import CreateView, MetaData, Select, Table, select
from sqlalchemy.dialects import postgresql

from old_news.db.models.feed import Feed
from old_news.db.models.host import Host
from old_news.db.models.item import Item
from old_news.db.models.page import host_failures, host_last_failure
from old_news.db.models.poll import FeedPoll, consecutive_failures, gone

# Kept out of `Base.metadata` so autogenerate never mistakes a view for a table it should
# create; alembic_utils owns their DDL instead.
_METADATA = MetaData()


def _sql(statement: Select) -> str:
    compiled = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return str(compiled)


def _view(name: str, statement: Select) -> tuple[Table, PGView]:
    """The table to query, and the entity Alembic compares against the database."""
    return (
        CreateView(statement, name, metadata=_METADATA).table,
        PGView(schema="public", signature=name, definition=_sql(statement)),
    )


_feed_health = select(
    Feed.id.label("feed_id"),
    Feed.url.label("url"),
    consecutive_failures(Feed.id).label("consecutive_failures"),
    gone(Feed.id).label("gone"),
    select(FeedPoll.outcome)
    .where(FeedPoll.feed_id == Feed.id)
    .order_by(FeedPoll.polled_at.desc())
    .limit(1)
    .scalar_subquery()
    .label("last_outcome"),
    Feed.last_success_at.label("last_success_at"),
    Feed.next_poll_at.label("next_poll_at"),
)

_host_health = select(
    Host.id.label("host_id"),
    Host.name.label("name"),
    host_failures(Host.id).label("capture_failures"),
    host_last_failure(Host.id).label("last_capture_failure"),
    Host.requires_www.label("requires_www"),
)

_item_reading = select(
    Item.id.label("item_id"),
    Item.reading_body.label("reading_body"),
)


feed_health, feed_health_view = _view("feed_health", _feed_health)
host_health, host_health_view = _view("host_health", _host_health)
item_reading, item_reading_view = _view("item_reading", _item_reading)

ENTITIES = [feed_health_view, host_health_view, item_reading_view]


def ours(obj: Any, *_: Any, **__: Any) -> bool:
    """Whether autogenerate should manage an object at all."""
    # alembic_utils drops anything it reflects and cannot find registered, which here is
    # the whole of procrastinate's machinery. This project owns views and nothing else.
    if isinstance(obj, ReplaceableEntity):
        return isinstance(obj, PGView) and not obj.signature.startswith("procrastinate_")
    return True


def register() -> None:
    """Tell autogenerate which views exist. Called from Alembic's env, once."""
    register_entities(ENTITIES)
