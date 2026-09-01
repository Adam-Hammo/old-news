"""Field values for the rows tests build, so no two look the same.

`DictFactory`, not `SQLAlchemyModelFactory`: factory_boy's ORM layer calls `session.flush()`
synchronously and every session here is an `AsyncSession`, and primary keys come from
`uuidv7()` on the server so an unsaved instance has no id for a `SubFactory` to point at.
So these produce kwargs and the fixtures that own a transaction do the inserting, in
dependency order, which is also what keeps one function to one transaction.

Callers override anything they assert on. What the factories are for is the rest — author,
tags, enclosures, published_at — which every test used to leave at its server default, so
nothing ever read a row where they were set.
"""

import datetime
from typing import Any, cast

import factory

from old_news.db import CAPTURE_POLICY, CaptureOutcome, ExtractionSource
from old_news.extract.article import EXTRACTOR, Article, extractor_version
from old_news.ingest.parser import parser_version


class Fields(factory.DictFactory):
    """Kwargs for one row. `kwargs()` rather than calling the factory, because factory_boy
    types a build as the factory class and `**` needs a checkable mapping."""

    class Meta:
        abstract = True

    @classmethod
    def kwargs(cls, **overrides: Any) -> dict[str, Any]:
        # `cast` because the stubs type a build as the factory class. `DictFactory` builds
        # `dict`, which is the whole reason these are declared as one.
        return cast("dict[str, Any]", cls(**overrides))


def faker():
    """The seeded instance the `Faker` declarations share, for use inside a lazy attribute."""
    return factory.Faker._get_faker()


def _digest() -> factory.Faker:
    """Something 32 bytes long. Never compared, only stored and constrained."""
    return factory.Faker("binary", length=32)


class FeedFields(Fields):
    url = factory.Sequence(lambda n: f"https://feed-{n}.example.com/feed.xml")
    title = factory.Faker("company")
    site_url = factory.Faker("uri")
    language = factory.Faker("language_code")
    platform = factory.Faker("word")
    # Far out, so a feed a test did not ask about never turns up in the poll sweep.
    next_poll_at = factory.LazyFunction(
        lambda: datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
    )


class ItemFields(Fields):
    guid = factory.Sequence(lambda n: f"guid-{n}")
    identity_key = factory.SelfAttribute("guid")
    identity_source = "guid"


class ItemVersionFields(Fields):
    title = factory.Faker("sentence", nb_words=8)
    author = factory.Faker("name")
    url = factory.Sequence(lambda n: f"https://article-{n}.example.com/story")
    canonical_url = factory.SelfAttribute("url")
    tags = factory.Faker("words", nb=3)
    comments_url = ""
    published_at = factory.Faker("date_time_this_year", tzinfo=datetime.UTC)
    updated_at = None
    content_hash = _digest()

    @factory.lazy_attribute
    def enclosures(self) -> list[dict[str, str]]:
        return [{"url": faker().uri(), "type": "audio/mpeg", "length": "1024"}]


class DocumentFields(Fields):
    status = 200
    body = b"<rss/>"
    body_hash = _digest()
    final_url = factory.Faker("uri")
    parse_ok = True


class PageCaptureFields(Fields):
    status = 200
    outcome = CaptureOutcome.OK
    body_hash = _digest()
    error = ""
    capture_policy = CAPTURE_POLICY


class FeedCaptureFields(Fields):
    body_hash = _digest()
    # The current one, or whatever holds this is due for re-carving and shows up in a sweep.
    parser_version = factory.LazyFunction(parser_version)


class ExtractionFields(Fields):
    source = ExtractionSource.FEED
    extractor = EXTRACTOR
    # Likewise: a reading by an older extractor leaves its version due.
    extractor_version = factory.LazyFunction(extractor_version)
    body = factory.Faker("paragraph", nb_sentences=20)
    links = factory.LazyFunction(list)

    # Measured off the body by the same code the extractor measures with, so a built row
    # cannot claim a shape its own text does not have — which is what the reading order
    # now sorts on. `str` for the type checker: inside a lazy attribute a sibling reads as
    # the declaration, and only at build time is it the string it resolved to.
    @factory.lazy_attribute
    def char_count(self) -> int:
        return Article(body=str(self.body)).char_count

    @factory.lazy_attribute
    def paragraph_count(self) -> int:
        return Article(body=str(self.body)).paragraph_count

    @factory.lazy_attribute
    def structure_count(self) -> int:
        return Article(body=str(self.body)).structure_count
