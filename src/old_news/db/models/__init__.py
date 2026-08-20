"""Importing this module registers every mapper. Alembic and the app both rely on it."""

from old_news.db.models.dictionary import ZstdDictionary
from old_news.db.models.document import Document
from old_news.db.models.extraction import (
    Extraction,
    ExtractionImage,
    ExtractionSource,
    FeedExtraction,
    ImageRole,
    PageExtraction,
)
from old_news.db.models.feed import Feed
from old_news.db.models.host import Host
from old_news.db.models.image import ImageCapture
from old_news.db.models.item import Item, ItemVersion
from old_news.db.models.page import PageCapture
from old_news.db.models.poll import FeedPoll, PollOutcome
from old_news.db.models.robots import RobotsPolicy
from old_news.db.models.subscription import Subscription
from old_news.db.models.training import Dimension, RuleSource, TrainingRule

__all__ = [
    "Dimension",
    "Document",
    "Extraction",
    "ExtractionImage",
    "ExtractionSource",
    "Feed",
    "FeedExtraction",
    "FeedPoll",
    "Host",
    "ImageCapture",
    "ImageRole",
    "Item",
    "ItemVersion",
    "PageCapture",
    "PageExtraction",
    "PollOutcome",
    "RobotsPolicy",
    "RuleSource",
    "Subscription",
    "TrainingRule",
    "ZstdDictionary",
]
