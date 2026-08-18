"""Importing this module registers every mapper. Alembic and the app both rely on it."""

from old_news.db.models.document import Document
from old_news.db.models.feed import Feed
from old_news.db.models.host import Host
from old_news.db.models.item import Item, ItemVersion
from old_news.db.models.robots import RobotsPolicy
from old_news.db.models.subscription import Subscription

__all__ = [
    "Document",
    "Feed",
    "Host",
    "Item",
    "ItemVersion",
    "RobotsPolicy",
    "Subscription",
]
