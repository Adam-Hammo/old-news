"""Capture against a real socket and a real Postgres."""

import datetime
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from old_news import db
from old_news.db import (
    CAPTURE_POLICY,
    CaptureOutcome,
    Host,
    PageCapture,
    RobotsPolicy,
    dictionaries,
)
from old_news.extract.capture import capture_page
from old_news.fetch import Fetcher
from old_news.politeness import ensure

PAGE = b"<html><head><title>An article</title></head><body><p>Words.</p></body></html>"
HTML = {"Content-Type": "text/html; charset=utf-8"}


@pytest.fixture
async def fetcher(settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


@pytest.fixture
def site(http_server) -> str:
    server = http_server(
        {
            "/article": (200, PAGE, HTML),
            "/moved": (301, b"", {"Location": "/article"}),
            "/video": (200, b"\x00" * 64, {"Content-Type": "video/mp4"}),
            "/gone": (404, b"Not here", HTML),
        }
    )
    return server


@pytest.fixture
def elsewhere(site: str, http_server) -> str:
    """A server whose article redirects to a different host on loopback."""
    away = site.replace("127.0.0.1", "localhost")
    return http_server({"/syndicated": (301, b"", {"Location": f"{away}/article"})})


@db.transactional
async def _captures(session: AsyncSession, version_id: uuid.UUID) -> list[PageCapture]:
    rows = await session.execute(
        select(PageCapture)
        .where(PageCapture.item_version_id == version_id)
        .order_by(PageCapture.fetched_at)
    )
    return list(rows.scalars().all())


@db.transactional
async def _body(session: AsyncSession, capture: PageCapture) -> bytes:
    return await dictionaries.expand(session, capture.body)


@db.transactional
async def _rules(session: AsyncSession, host: str, body: str) -> None:
    """One row per host, last write winning: several versions can share a host."""
    await session.execute(
        insert(RobotsPolicy)
        .values(
            host_id=await ensure(session, host),
            body=body,
            status=200,
            expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
        )
        .on_conflict_do_update(index_elements=["host_id"], set_={"body": body})
    )


async def _version(feed_id: uuid.UUID, article, url: str) -> uuid.UUID:
    """A version to capture, with the host's robots.txt already asked for."""
    await _rules("127.0.0.1", "")
    return (await article(feed_id, ("An article", url)))[0]


async def test_a_page_is_captured_and_reads_back(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    version_id = await _version(feed_id, article, f"{site}/article")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.status == 200
    assert await _body(stored) == PAGE


async def test_a_redirect_records_both_urls(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """The extractor needs the URL the page actually came from."""
    version_id = await _version(feed_id, article, f"{site}/moved")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.url.endswith("/moved")
    assert stored.final_url.endswith("/article")


async def test_a_non_html_body_is_refused_without_being_stored(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """An aggregator points at video and PDFs, and the body cap is 16 MB."""
    version_id = await _version(feed_id, article, f"{site}/video")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.body == b""
    assert stored.status == 0
    assert "video/mp4" in stored.error


async def test_a_404_is_recorded_rather_than_dropped(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """The row is what bounds the retry."""
    version_id = await _version(feed_id, article, f"{site}/gone")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.status == 404


async def test_a_disallowed_host_is_never_fetched(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """The strict check, with no blanket-ban carve-out."""
    version_id = await _version(feed_id, article, f"{site}/article")
    await _rules("127.0.0.1", "User-agent: *\nDisallow: /\n")

    stored = await capture_page(version_id, fetcher, settings)

    # Recorded, though nothing was sent. The sweep works out what it has already been
    # told no about from these rows, and a decision that returns silently tells it
    # nothing — so it hands the same version the same slot every minute.
    assert stored is not None and stored.outcome == CaptureOutcome.DISALLOWED
    assert stored.status == 0


async def test_two_attempts_on_one_version_leave_two_rows(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """Append-only. A 403 on Tuesday and the page on Friday are both facts."""
    version_id = await _version(feed_id, article, f"{site}/gone")

    await capture_page(version_id, fetcher, settings)
    await capture_page(version_id, fetcher, settings)

    assert len(await _captures(version_id)) == 2


async def test_the_same_page_from_two_feeds_is_stored_once(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """204 URLs in this corpus arrive in more than one feed."""
    first = await _version(feed_id, article, f"{site}/article")
    second = await _version(feed_id, article, f"{site}/article")

    one = await capture_page(first, fetcher, settings)
    two = await capture_page(second, fetcher, settings)

    assert one is not None and two is not None
    assert one.body_hash == two.body_hash
    assert one.body == two.body
    assert await _body(two) == PAGE


async def test_the_article_host_gets_a_row(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """`host_id` is a key, not a string re-derived at read time."""
    version_id = await _version(feed_id, article, f"{site}/article")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    async with db.session() as session:
        name = (
            await session.execute(select(Host.name).where(Host.id == stored.host_id))
        ).scalar_one()
    assert name == "127.0.0.1"


async def test_a_host_whose_rules_were_never_read_is_not_fetched(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """For a job queued before a rule existed."""
    version_id = (await article(feed_id, ("An article", f"{site}/article")))[0]

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None and stored.outcome == CaptureOutcome.UNKNOWN_RULES


async def test_a_redirect_to_another_host_is_checked_against_that_host(
    clean: None, no_policies: None, feed_id, article, elsewhere: str, fetcher, settings
):
    """Only the first host was ever asked."""
    version_id = await _version(feed_id, article, f"{elsewhere}/syndicated")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.body == b""
    assert "redirected to localhost" in stored.error


async def test_a_redirect_to_a_host_that_does_allow_it_is_kept(
    clean: None, no_policies: None, feed_id, article, elsewhere: str, fetcher, settings
):
    """The guard is about asking, not refusing."""
    version_id = await _version(feed_id, article, f"{elsewhere}/syndicated")
    await _rules("localhost", "")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.status == 200
    assert await _body(stored) == PAGE


async def _other_article(feed_id: uuid.UUID, article) -> uuid.UUID:
    """A second article on the same host, to hang the host's refusals on."""
    return (await article(feed_id, ("Another article", "https://127.0.0.1/elsewhere")))[0]


async def test_a_host_refusing_everything_stops_being_asked(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings, captures
):
    """One clock for the publisher, not one per article."""
    version_id = await _version(feed_id, article, f"{site}/article")
    await captures(
        await _other_article(feed_id, article),
        status=403,
        times=settings.extract.host_failure_threshold,
        ago=datetime.timedelta(minutes=1),
        host="127.0.0.1",
        url="https://127.0.0.1/other",
    )

    stored = await capture_page(version_id, fetcher, settings)

    # Recorded, and harmless to record: only `failed` is counted against a host, so the
    # row cannot move the breaker that wrote it.
    assert stored is not None and stored.outcome == CaptureOutcome.REFUSED


async def test_a_host_below_the_threshold_is_still_asked(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings, captures
):
    """A run of failures short of the threshold is bad luck on individual articles."""
    version_id = await _version(feed_id, article, f"{site}/article")
    await captures(
        await _other_article(feed_id, article),
        status=403,
        times=settings.extract.host_failure_threshold - 1,
        ago=datetime.timedelta(minutes=1),
        host="127.0.0.1",
        url="https://127.0.0.1/other",
    )

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None and stored.status == 200


async def test_one_probe_is_let_through_once_the_interval_passes(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings, captures
):
    """Without it the breaker freezes the window it reads."""
    version_id = await _version(feed_id, article, f"{site}/article")
    await captures(
        await _other_article(feed_id, article),
        status=403,
        times=settings.extract.host_failure_threshold,
        ago=datetime.timedelta(seconds=settings.extract.host_probe.minimum_seconds + 60),
        host="127.0.0.1",
        url="https://127.0.0.1/other",
    )

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None and stored.status == 200


async def test_a_run_of_404s_does_not_close_a_host(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings, captures
):
    """A 404 is about one URL."""
    version_id = await _version(feed_id, article, f"{site}/article")
    await captures(
        await _other_article(feed_id, article),
        status=404,
        outcome=CaptureOutcome.GONE,
        times=settings.extract.host_failure_threshold * 2,
        ago=datetime.timedelta(minutes=1),
        host="127.0.0.1",
        url="https://127.0.0.1/other",
    )

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None and stored.status == 200


async def test_a_capture_records_the_policy_it_was_made_under(
    clean: None, no_policies: None, feed_id, article, site: str, fetcher, settings
):
    """Unstamped rows fall back to the default and are forgiven forever."""
    version_id = await _version(feed_id, article, f"{site}/article")

    stored = await capture_page(version_id, fetcher, settings)

    assert stored is not None
    assert stored.capture_policy == CAPTURE_POLICY
