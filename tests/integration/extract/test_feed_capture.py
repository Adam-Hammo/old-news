"""Carving item text back out of a stored document, against a real Postgres."""

import datetime
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from old_news import db, extract
from old_news.config import ExtractSettings, Settings
from old_news.db import Document, FeedCapture, FeedExtraction, Item, ItemVersion, dictionaries
from old_news.db import bytes as codec
from old_news.extract.feed import capture_feed
from old_news.extract.service import extract_feed
from old_news.ingest import parser, store

SETTINGS = Settings(_env_file=None)
EXTRACT = ExtractSettings()

PARAGRAPH = "A paragraph with enough words in it to look like prose. " * 12
ARTICLE = f"<p>{PARAGRAPH}</p>" * 4


def _document(*entries: str) -> bytes:
    """A feed document whose items are whatever XML fragments are handed over."""
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<title>Loopback News</title><link>https://loopback.example.com/</link>"
        f"{''.join(entries)}"
        "</channel></rss>"
    ).encode()


def _entry(guid: str, *, content: str = "", summary: str = "") -> str:
    body = f"<content:encoded><![CDATA[{content}]]></content:encoded>" if content else ""
    described = f"<description><![CDATA[{summary}]]></description>" if summary else ""
    return (
        f"<item><guid>{guid}</guid>"
        f"<link>https://loopback.example.com/{guid}</link>"
        f"<title>Story {guid}</title>{described}{body}</item>"
    )


def _parse(body: bytes, url: str | None = None):
    return parser.parse(body, url=url or "https://loopback.example.com/feed.xml")


@db.transactional
async def _ingest(
    session: AsyncSession, feed_id: uuid.UUID, body: bytes, *, served_from: str = ""
) -> uuid.UUID:
    """A poll's writes, without the fetch: this is the document a carving reads back."""
    feed = await session.get_one(db.Feed, feed_id)
    parsed = _parse(body, url=served_from or None)
    document = Document(
        feed_id=feed_id,
        final_url=served_from,
        status=200,
        body_hash=body[:32],
        body=body,
    )
    session.add(document)
    await session.flush()
    await store.apply_items(
        session, feed, document, parsed.items, observed_at=datetime.datetime.now(datetime.UTC)
    )
    return document.id


@db.transactional
async def _captures(session: AsyncSession, document_id: uuid.UUID) -> list[FeedCapture]:
    rows = await session.execute(
        select(FeedCapture)
        .where(FeedCapture.document_id == document_id)
        .order_by(FeedCapture.captured_at, FeedCapture.id)
    )
    return list(rows.scalars().all())


@db.transactional
async def _text(session: AsyncSession, capture: FeedCapture) -> str:
    return (await dictionaries.expand(session, capture.body)).decode()


@db.transactional
async def _version_of(session: AsyncSession, guid: str) -> uuid.UUID:
    return (
        await session.execute(
            select(ItemVersion.id)
            .join(Item, Item.id == ItemVersion.item_id)
            .where(Item.guid == guid)
        )
    ).scalar_one()


async def test_content_bearing_text_round_trips(clean: None, feed_id):
    """Ingest, carve, expand: what the feed said comes back byte for byte."""
    document_id = await _ingest(feed_id, _document(_entry("a", content=ARTICLE)))

    assert await capture_feed(document_id, SETTINGS) == 1

    (capture,) = await _captures(document_id)
    assert await _text(capture) == ARTICLE
    assert capture.parser_version == parser.parser_version()


async def test_a_summary_only_version_gets_a_capture_and_a_reading(clean: None, feed_id):
    """The hole this closes: a feed that carries only a summary used to get no extraction
    at all, because the sweep asked for `content` and only `content`."""
    document_id = await _ingest(feed_id, _document(_entry("a", summary=ARTICLE)))
    await capture_feed(document_id, SETTINGS)
    version_id = await _version_of("a")

    assert await extract.due_feed_extractions(50) == [version_id]
    reading = await extract_feed(version_id, EXTRACT)

    assert reading is not None
    assert PARAGRAPH.strip() in reading.body


async def test_a_version_the_feed_said_nothing_about_still_gets_a_row(clean: None, feed_id):
    """Or the sweep offers this document again every two minutes for as long as we hold it."""
    document_id = await _ingest(feed_id, _document(_entry("a")))

    await capture_feed(document_id, SETTINGS)

    (capture,) = await _captures(document_id)
    assert capture.body == b""
    assert await extract.due_feed_captures(50) == []
    assert await extract.due_feed_extractions(50) == []


async def test_the_sweep_offers_a_document_once(clean: None, feed_id):
    document_id = await _ingest(feed_id, _document(_entry("a", content="<p>Words.</p>")))

    assert await extract.due_feed_captures(50) == [document_id]
    await capture_feed(document_id, SETTINGS)
    assert await extract.due_feed_captures(50) == []


async def test_one_parse_serves_every_version_the_document_carries(clean: None, feed_id):
    entries = [_entry(guid, content=f"<p>{guid}</p>{ARTICLE}") for guid in ("a", "b", "c")]
    document_id = await _ingest(feed_id, _document(*entries))

    assert await extract.due_feed_captures(50) == [document_id]
    assert await capture_feed(document_id, SETTINGS) == 3
    assert len(await _captures(document_id)) == 3


async def test_re_carving_unchanged_text_moves_the_stamp(clean: None, feed_id, stored_feed_text):
    """What the migration hands over: a row whose text is right and whose provenance is
    not. Unchanged bytes conflict, so the row already there is the one re-attributed —
    and it has to be, or the sweep offers this document forever."""
    document_id = await _ingest(feed_id, _document(_entry("a", content=ARTICLE)))
    version_id = await _version_of("a")
    await stored_feed_text(version_id, ARTICLE, parser_version="unknown")

    assert await extract.due_feed_captures(50) == [document_id]
    await capture_feed(document_id, SETTINGS)

    (capture,) = await _captures(document_id)
    assert capture.parser_version == parser.parser_version()
    assert await extract.due_feed_captures(50) == []


async def test_a_second_carving_supersedes_the_first(clean: None, feed_id, stored_feed_text):
    """Append-only, so the earlier one stays; the reading path takes the later one."""
    document_id = await _ingest(feed_id, _document(_entry("a", content=ARTICLE)))
    await capture_feed(document_id, SETTINGS)
    version_id = await _version_of("a")

    rewritten = await stored_feed_text(version_id, f"<p>Rewritten.</p>{ARTICLE}")

    assert len(await _captures(document_id)) == 2
    reading = await extract_feed(version_id, EXTRACT)
    assert isinstance(reading, FeedExtraction)
    assert reading.feed_capture_id == rewritten
    assert "Rewritten" in reading.body


async def test_a_carving_is_compressed_against_its_feed_dictionary(clean: None, feed_id):
    """Item text is its own dictionary scope: fragments, not whole feed XML."""
    trained = dictionaries.train(
        [f"{ARTICLE}<p>{n}</p>".encode() for n in range(30)], SETTINGS.storage
    )
    assert trained is not None
    stored = await dictionaries.store(db.DictionaryScope.FEED_ITEM, feed_id, trained)

    document_id = await _ingest(feed_id, _document(_entry("a", content=ARTICLE)))
    await capture_feed(document_id, SETTINGS)

    (capture,) = await _captures(document_id)
    assert capture.dictionary_id == stored.id
    assert codec.dictionary_id(capture.body) == trained.dict_id
    assert await _text(capture) == ARTICLE


async def test_a_feed_keeps_a_dictionary_per_kind_of_body(clean: None, feed_id):
    """`(dict_id, feed_id, host_id)` could not hold both; the scope is what tells them apart."""
    documents = dictionaries.train([_document(_entry(str(n))) for n in range(30)], SETTINGS.storage)
    items = dictionaries.train(
        [f"{ARTICLE}<p>{n}</p>".encode() for n in range(30)], SETTINGS.storage
    )
    assert documents is not None and items is not None

    for scope, trained in (
        (db.DictionaryScope.FEED_DOCUMENT, documents),
        (db.DictionaryScope.FEED_ITEM, items),
    ):
        await dictionaries.store(scope, feed_id, trained)

    async with db.session() as session:
        held = (
            await session.execute(
                select(func.count())
                .select_from(db.ZstdDictionary)
                .where(db.ZstdDictionary.feed_id == feed_id)
            )
        ).scalar_one()

    assert held == 2
    for scope, trained in (
        (db.DictionaryScope.FEED_DOCUMENT, documents),
        (db.DictionaryScope.FEED_ITEM, items),
    ):
        async with db.session() as session:
            current = await dictionaries.current_for_feed(session, feed_id, scope)
        assert current is not None
        assert current.dictionary.dict_id == trained.dict_id


async def test_a_carving_can_be_rebuilt_from_the_document_alone(clean: None, feed_id):
    """What makes `documents.body` the archive: bin every carving and the sweep puts the
    same bytes back. It is the only copy of this text now, so that has to be a property
    rather than a claim in a migration message."""
    document_id = await _ingest(
        feed_id, _document(_entry("a", content=ARTICLE), _entry("b", summary=ARTICLE))
    )
    await capture_feed(document_id, SETTINGS)
    before = {c.item_version_id: await _text(c) for c in await _captures(document_id)}
    assert len(before) == 2

    async with db.session() as session:
        await session.execute(delete(FeedCapture).where(FeedCapture.document_id == document_id))

    assert await extract.due_feed_captures(50) == [document_id]
    await capture_feed(document_id, SETTINGS)

    after = {c.item_version_id: await _text(c) for c in await _captures(document_id)}
    assert after == before


# No `<channel><link>`, and entry links relative to whatever served the document.
MOVED = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>Loopback</title>'
    f"<item><title>A story</title><link>a-story</link>"
    f"<description><![CDATA[{ARTICLE}]]></description></item>"
    "</channel></rss>"
).encode()


async def test_a_redirecting_feed_re_carves_to_the_same_identity(clean: None, feed_id):
    """The parse at ingest used the URL the document came back from, so a re-parse has to
    as well. Reading `feeds.url` instead re-reads every relative link against the wrong
    base, matches no version, and carves the whole feed to nothing."""
    served_from = "https://loopback.example.com/blog/feed.xml"
    document_id = await _ingest(feed_id, MOVED, served_from=served_from)

    assert await capture_feed(document_id, SETTINGS) == 1

    (capture,) = await _captures(document_id)
    assert await _text(capture) == ARTICLE


async def test_a_carving_that_finds_nothing_leaves_the_one_it_held(
    clean: None, feed_id, stored_feed_text
):
    """The failure mode of writing an empty row: `feed_capture` takes the newest, so text
    an earlier parse found would be hidden for good — `has_feed_text` goes false and no
    later extractor bump can reach it again."""
    # A document the current parser can make nothing of, so no entry matches its version.
    document_id = await _ingest(feed_id, _document(_entry("a", content=ARTICLE)))
    version_id = await _version_of("a")
    held = await stored_feed_text(version_id, ARTICLE, parser_version="unknown")

    async with db.session() as session:
        await session.execute(
            update(Document).where(Document.id == document_id).values(body=b"<rss/>")
        )

    assert await capture_feed(document_id, SETTINGS) == 1

    async with db.session() as session:
        version = (
            await session.execute(
                select(ItemVersion)
                .where(ItemVersion.id == version_id)
                .options(joinedload(ItemVersion.feed_capture))
            )
        ).scalar_one()
        assert version.feed_capture is not None
        assert version.feed_capture.id == held
        assert version.feed_capture.parser_version == parser.parser_version()
        assert version.has_feed_text

    assert await extract.due_feed_captures(50) == []


async def test_a_repeated_identity_keeps_the_entry_the_version_was_made_from(clean: None, feed_id):
    """`apply_items` takes the first of a repeated identity, so the carving has to as well
    or the stored text belongs to an entry that was thrown away."""
    first, second = f"<p>the first entry</p>{ARTICLE}", f"<p>the second entry</p>{ARTICLE}"
    document_id = await _ingest(
        feed_id, _document(_entry("a", content=first), _entry("a", content=second))
    )

    await capture_feed(document_id, SETTINGS)

    (capture,) = await _captures(document_id)
    assert await _text(capture) == first


async def test_has_feed_text_reads_the_newest_carving(clean: None, feed_id, stored_feed_text):
    """The newest, not any: `pending_feed` expands that one, so a sweep asking anything
    wider hands it a version it returns nothing for and the job does no work forever."""
    await _ingest(feed_id, _document(_entry("a", content=ARTICLE)))
    version_id = await _version_of("a")
    await stored_feed_text(version_id, ARTICLE)
    await stored_feed_text(version_id, "")

    async with db.session() as session:
        assert not (
            await session.execute(
                select(ItemVersion.has_feed_text).where(ItemVersion.id == version_id)
            )
        ).scalar_one()

    assert version_id not in await extract.due_feed_extractions(50)
