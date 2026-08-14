"""Importing this module registers every mapper. Alembic and the app both rely on it."""

from old_news.db.models.document import Document
from old_news.db.models.feed import Feed
from old_news.db.models.item import IDENTITY_SOURCES, Item, ItemVersion
from old_news.db.models.subscription import Subscription

__all__ = ["IDENTITY_SOURCES", "Document", "Feed", "Item", "ItemVersion", "Subscription"]
