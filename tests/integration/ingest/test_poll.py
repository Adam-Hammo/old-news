import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TypedDict

import pytest
from sqlalchemy import event, func, select

from old_news import db
from old_news.config import Settings
from old_news.db import Document, Feed, Item, ItemVersion, Subscription
from old_news.fetch import Fetcher
from old_news.ingest.service import poll_feed


def document(title: str, *, second: str = "Second article") -> bytes:
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Loopback News</title><link>https://loopback.example.com/</link>
      <item><title>{title}</title><link>https://loopback.example.com/a</link>
        <guid>item-a</guid><description>Body A</description></item>
      <item><title>{second}</title><link>https://loopback.example.com/b</link>
        <guid>item-b</guid><description>Body B</description></item>
    </channel></rss>""".encode()


class Serving(TypedDict):
    body: bytes
    etag: str
    status: int
    retry_after: str


STATE: Serving = {
    "body": document("First article"),
    "etag": '"v1"',
    "status": 200,
    "retry_after": "120",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if STATE["status"] != 200:
            self.send_response(STATE["status"])
            self.send_header("Retry-After", STATE["retry_after"])
            self.end_headers()
            return

        if self.headers.get("If-None-Match") == STATE["etag"]:
            self.send_response(304)
            self.send_header("ETag", STATE["etag"])
            self.end_headers()
            return

        body = STATE["body"]
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("ETag", STATE["etag"])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/feed.xml"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def feed_state() -> Iterator[Serving]:
    STATE.update(body=document("First article"), etag='"v1"', status=200, retry_after="120")
    yield STATE


@pytest.fixture
async def feed(clean: None, server: str, feed_state: Serving) -> AsyncIterator[Feed]:
    async with db.session() as session:
        row = Feed(url=server, title="")
        session.add(row)
        await session.flush()
        session.add(Subscription(feed_id=row.id))
    # Outside the block: the transaction has to commit before the poller, on its
    # own session, can see the feed.
    yield row


@pytest.fixture
async def fetcher(settings: Settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


async def counts() -> dict[str, int]:
    async with db.session() as session:
        return {
            name: (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for name, model in (("documents", Document), ("items", Item), ("versions", ItemVersion))
        }


async def test_first_poll_stores_document_items_and_versions(feed, fetcher, settings):
    applied = await poll_feed(feed.id, fetcher, settings)

    assert applied.new_items == 2
    assert await counts() == {"documents": 1, "items": 2, "versions": 2}

    async with db.session() as session:
        versions = (await session.execute(select(ItemVersion))).scalars().all()
    assert all(v.supersedes_id is None for v in versions), "first versions start a chain"


async def test_unchanged_body_writes_no_second_document(feed, fetcher, settings):
    await poll_feed(feed.id, fetcher, settings)
    STATE["etag"] = '"v2"'  # force a 200 rather than a 304

    await poll_feed(feed.id, fetcher, settings)

    assert await counts() == {"documents": 1, "items": 2, "versions": 2}


async def test_not_modified_short_circuits(feed, fetcher, settings):
    await poll_feed(feed.id, fetcher, settings)

    applied = await poll_feed(feed.id, fetcher, settings)

    assert applied.new_items == 0
    assert await counts() == {"documents": 1, "items": 2, "versions": 2}


async def test_an_edit_appends_a_version_and_keeps_the_original(feed, fetcher, settings):
    await poll_feed(feed.id, fetcher, settings)
    STATE.update(body=document("First article, corrected"), etag='"v2"')

    await poll_feed(feed.id, fetcher, settings)

    assert await counts() == {"documents": 2, "items": 2, "versions": 3}

    async with db.session() as session:
        chain = (
            (
                await session.execute(
                    select(ItemVersion)
                    .join(Item, Item.id == ItemVersion.item_id)
                    .where(Item.identity_key == "item-a")
                    .order_by(ItemVersion.id)
                )
            )
            .scalars()
            .all()
        )

    assert [v.title for v in chain] == ["First article", "First article, corrected"]
    assert chain[1].supersedes_id == chain[0].id


async def test_read_state_survives_an_edit(feed, fetcher, settings):
    await poll_feed(feed.id, fetcher, settings)

    async with db.session() as session:
        item = (
            await session.execute(select(Item).where(Item.identity_key == "item-a"))
        ).scalar_one()
        item.read = True

    STATE.update(body=document("First article, corrected"), etag='"v2"')
    await poll_feed(feed.id, fetcher, settings)

    async with db.session() as session:
        item = (
            await session.execute(select(Item).where(Item.identity_key == "item-a"))
        ).scalar_one()

    assert item.read is True


async def test_a_poll_updates_only_the_feeds_table(feed, fetcher, settings):
    """The invariant the archive rests on: ingestion appends everywhere else.

    Asserted on the statements rather than the values, because the point is what
    a poll is capable of, not what it happened to do this time.
    """
    await poll_feed(feed.id, fetcher, settings)
    STATE.update(body=document("First article, corrected"), etag='"v2"')

    statements: list[str] = []

    @event.listens_for(db.engine().sync_engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    await poll_feed(feed.id, fetcher, settings)

    mutations = [s for s in statements if s.upper().startswith(("UPDATE", "DELETE"))]

    assert mutations, "the poll should have rescheduled the feed"
    assert all(s.upper().startswith("UPDATE FEEDS") for s in mutations), mutations


async def _wait_after_poll(feed, fetcher, settings) -> float:
    await poll_feed(feed.id, fetcher, settings)
    async with db.session() as session:
        row = await session.get(Feed, feed.id)
        assert row is not None and row.last_polled_at is not None
        return (row.next_poll_at - row.last_polled_at).total_seconds()


async def test_a_short_retry_after_is_a_floor_not_a_target(feed, fetcher, settings):
    """Retry-After asks us to wait *at least* this long, so our own minimum still applies."""
    STATE.update(status=503, retry_after="120")

    wait = await _wait_after_poll(feed, fetcher, settings)

    assert wait >= 120
    assert wait == settings.ingest.min_interval_seconds


async def test_a_long_retry_after_overrides_the_backoff_policy(feed, fetcher, settings):
    STATE.update(status=503, retry_after="7200")

    wait = await _wait_after_poll(feed, fetcher, settings)

    assert wait == 7200


async def test_a_dated_retry_after_falls_back_to_the_maximum(feed, fetcher, settings):
    """The header may be an HTTP date; backing right off is the safe reading."""
    STATE.update(status=503, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")

    wait = await _wait_after_poll(feed, fetcher, settings)

    assert wait == settings.ingest.max_interval_seconds


async def test_a_crash_still_moves_the_schedule(feed, fetcher, settings, monkeypatch):
    """Otherwise the feed stays due and the scheduler re-defers it every minute."""
    import pytest as _pytest

    from old_news.ingest import parser

    def explode(*args, **kwargs):
        raise ValueError("unparsable")

    monkeypatch.setattr(parser, "parse", explode)

    with _pytest.raises(ValueError):
        await poll_feed(feed.id, fetcher, settings)

    async with db.session() as session:
        row = await session.get(Feed, feed.id)
        assert row is not None and row.last_polled_at is not None

    assert row.next_poll_at > row.last_polled_at
    assert row.consecutive_failures == 1
    assert "unparsable" in row.last_error
