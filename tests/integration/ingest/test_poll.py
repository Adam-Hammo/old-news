from collections.abc import AsyncIterator, Iterator
from typing import TypedDict

import pytest
from sqlalchemy import event, func, select

from old_news import db
from old_news.config import Settings
from old_news.db import (
    Document,
    Feed,
    FeedPoll,
    Item,
    ItemVersion,
    PollOutcome,
    RobotsPolicy,
    Subscription,
)
from old_news.fetch import Fetcher
from old_news.ingest import parser, schedule
from old_news.ingest.service import poll_feed
from old_news.politeness import ensure, resolve


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


def _serve(headers: dict[str, str]):
    """One route whose answer depends on STATE, so a test can change what the
    publisher is doing without restarting anything."""
    if STATE["status"] != 200:
        # An empty `retry_after` means the publisher sent no header at all.
        asked = {"Retry-After": STATE["retry_after"]} if STATE["retry_after"] else {}
        return STATE["status"], b"", asked
    if headers.get("if-none-match") == STATE["etag"]:
        return 304, b"", {"ETag": STATE["etag"]}
    return (
        200,
        STATE["body"],
        {"Content-Type": "application/rss+xml", "ETag": STATE["etag"]},
    )


@pytest.fixture
def server(http_server) -> str:
    return f"{http_server({'/feed.xml': _serve})}/feed.xml"


@pytest.fixture
def feed_state() -> Iterator[Serving]:
    STATE.update(body=document("First article"), etag='"v1"', status=200, retry_after="120")
    yield STATE


@pytest.fixture
async def feed(clean: None, server: str, feed_state: Serving) -> AsyncIterator[Feed]:
    async with db.session() as session:
        row = Feed(url=server, title="", host_id=await resolve(session, server))
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
    """The invariant the archive rests on. Asserted on the statements, not the values."""
    await poll_feed(feed.id, fetcher, settings)
    STATE.update(body=document("First article, corrected"), etag='"v2"')

    statements: list[str] = []

    @event.listens_for(db.engine().sync_engine, "before_cursor_execute")
    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
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


async def test_a_rate_limit_with_no_retry_after_uses_the_backoff_policy(feed, fetcher, settings):
    """Absent is not unparsable: a bare 503 is an ordinary failure, not a day off."""
    STATE.update(status=503, retry_after="")

    wait = await _wait_after_poll(feed, fetcher, settings)

    assert wait < settings.ingest.max_interval_seconds
    assert wait == schedule.next_interval(settings.ingest, failures=1)


async def test_a_crash_still_moves_the_schedule(feed, fetcher, settings, monkeypatch):
    """Otherwise the feed stays due and the scheduler re-defers it every minute."""

    def explode(*_args, **_kwargs):
        raise ValueError("unparsable")

    monkeypatch.setattr(parser, "parse", explode)

    with pytest.raises(ValueError):
        await poll_feed(feed.id, fetcher, settings)

    async with db.session() as session:
        row = await session.get(Feed, feed.id)
        assert row is not None and row.last_polled_at is not None

    assert row.next_poll_at > row.last_polled_at
    assert await _failure_state(feed.id) == (1, False)
    outcome, error = (await _polls(feed.id))[-1]
    assert outcome == PollOutcome.FAILED
    assert "unparsable" in error


async def _failure_state(feed_id) -> tuple[int, bool]:
    """The two derived properties, which only exist as SQL."""
    async with db.session() as session:
        row = (
            await session.execute(
                select(Feed.consecutive_failures, Feed.gone).where(Feed.id == feed_id)
            )
        ).one()
        return row.consecutive_failures, row.gone


async def _polls(feed_id) -> list[tuple[str, str]]:
    """What the log recorded, newest last."""
    async with db.session() as session:
        rows = await session.execute(
            select(FeedPoll.outcome, FeedPoll.error)
            .where(FeedPoll.feed_id == feed_id)
            .order_by(FeedPoll.polled_at)
        )
        return [(outcome, error) for outcome, error in rows.all()]


async def _store_policy(host: str, body: str) -> None:
    async with db.session() as session:
        session.add(RobotsPolicy(host_id=await ensure(session, host), body=body, status=200))


async def test_a_targeted_disallow_stops_the_poll(feed, fetcher, settings, no_policies):
    """The feed is named in robots.txt, so it is left alone."""
    await _store_policy("127.0.0.1", "User-agent: *\nDisallow: /feed.xml\n")

    applied = await poll_feed(feed.id, fetcher, settings)

    assert applied.new_items == 0
    assert await counts() == {"documents": 0, "items": 0, "versions": 0}


async def test_a_disallowed_feed_backs_off_without_being_suspended(
    feed, fetcher, settings, no_policies
):
    """Dropping the rule has to bring the feed back on its own, so nothing is
    suspended and no failure is counted."""
    await _store_policy("127.0.0.1", "User-agent: *\nDisallow: /feed.xml\n")

    await poll_feed(feed.id, fetcher, settings)

    assert await _polls(feed.id) == [(PollOutcome.DISALLOWED, "disallowed by robots.txt")]

    async with db.session() as session:
        stored = await session.get(Feed, feed.id)
        assert stored is not None
        assert stored.last_polled_at is not None
        assert stored.next_poll_at > stored.last_polled_at

    assert await _failure_state(feed.id) == (0, False)


async def test_a_blanket_ban_still_polls(feed, fetcher, settings, no_policies):
    """RSS is published for readers; a site banning all bots hasn't withdrawn it."""
    await _store_policy("127.0.0.1", "User-agent: *\nDisallow: /\n")

    applied = await poll_feed(feed.id, fetcher, settings)

    assert applied.new_items == 2


async def test_one_document_repeating_an_identity_does_not_fail_the_poll(feed, fetcher, settings):
    """The repeat used to raise and fail every poll of that feed. The first entry wins."""
    duplicated = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Broken</title>
      <item><title>First</title><guid>same</guid><description>A</description></item>
      <item><title>Second</title><guid>same</guid><description>B</description></item>
    </channel></rss>"""
    STATE.update(body=duplicated, etag='"dupe"')

    applied = await poll_feed(feed.id, fetcher, settings)

    assert applied.new_items == 1
    assert applied.duplicate_identity == 1
    assert (await counts())["items"] == 1

    assert await _failure_state(feed.id) == (0, False)
