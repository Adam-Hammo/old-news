"""Importing this module registers every mapper. Alembic and the app both rely on it."""

from old_news.db.models.dictionary import DictionaryScope, ZstdDictionary
from old_news.db.models.document import Document
from old_news.db.models.extraction import (
    READING_IDENTITY,
    READING_KEY,
    Extraction,
    ExtractionImage,
    ExtractionSource,
    FeedExtraction,
    ImageRole,
    PageExtraction,
)
from old_news.db.models.feed import Feed
from old_news.db.models.feed_capture import FeedCapture
from old_news.db.models.host import Host
from old_news.db.models.image import ImageCapture
from old_news.db.models.item import Item, ItemVersion
from old_news.db.models.page import CAPTURE_POLICY, CaptureOutcome, PageCapture
from old_news.db.models.poll import FeedPoll, PollOutcome
from old_news.db.models.rendition import (
    RENDITION_IDENTITY,
    RENDITION_KEY,
    ImageRendition,
)
from old_news.db.models.robots import RobotsPolicy
from old_news.db.models.subscription import Subscription
from old_news.db.models.training import Dimension, RuleSource, TrainingRule

__all__ = [
    "CAPTURE_POLICY",
    "READING_IDENTITY",
    "READING_KEY",
    "RENDITION_IDENTITY",
    "RENDITION_KEY",
    "CaptureOutcome",
    "DictionaryScope",
    "Dimension",
    "Document",
    "Extraction",
    "ExtractionImage",
    "ExtractionSource",
    "Feed",
    "FeedCapture",
    "FeedExtraction",
    "FeedPoll",
    "Host",
    "ImageCapture",
    "ImageRendition",
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
