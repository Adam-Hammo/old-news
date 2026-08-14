import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import select

from old_news import db
from old_news.config import Settings
from old_news.db import Feed, Subscription
from old_news.fetch import Fetcher
from old_news.subscriptions.service import import_opml

SITE = b"""<!doctype html><html><head>
  <link rel="alternate" type="application/rss+xml" href="/discovered.xml">
</head><body>A blog</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/blog/":
            self._send(200, SITE, "text/html")
        elif self.path == "/nothing/":
            self._send(200, b"<html><head></head></html>", "text/html")
        else:
            self._send(404, b"")

    def _send(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
async def fetcher(settings: Settings) -> AsyncIterator[Fetcher]:
    client = Fetcher(settings.http)
    yield client
    await client.aclose()


def opml_for(site: str) -> bytes:
    return f"""<?xml version="1.0"?>
    <opml version="2.0"><body>
      <outline text="News" title="News">
        <outline text="Direct" type="rss" xmlUrl="https://direct.example.com/feed.xml"/>
      </outline>
      <outline text="Blog" htmlUrl="{site}/blog/"/>
      <outline text="Feedless" htmlUrl="{site}/nothing/"/>
    </body></opml>""".encode()


async def test_import_adds_feeds_and_discovers_where_needed(clean, site, fetcher):
    result = await import_opml(opml_for(site), fetcher)

    assert result.added == 2
    assert result.undiscoverable == (f"{site}/nothing/",)

    async with db.session() as session:
        urls = set((await session.execute(select(Feed.url))).scalars().all())

    assert urls == {"https://direct.example.com/feed.xml", f"{site}/discovered.xml"}


async def test_folder_titles_become_categories(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    async with db.session() as session:
        rows = (
            await session.execute(
                select(Feed.url, Subscription.category).join(
                    Subscription, Subscription.feed_id == Feed.id
                )
            )
        ).all()

    assert dict(rows)["https://direct.example.com/feed.xml"] == "News"


async def test_a_discovered_feed_records_the_site_it_came_from(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    async with db.session() as session:
        feed = (
            await session.execute(select(Feed).where(Feed.url == f"{site}/discovered.xml"))
        ).scalar_one()

    assert feed.site_url == f"{site}/blog/"


async def test_importing_the_same_file_twice_adds_nothing(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    result = await import_opml(opml_for(site), fetcher)

    assert result.added == 0
    assert result.already_present == 2


async def test_every_feed_gets_exactly_one_subscription(clean, site, fetcher):
    await import_opml(opml_for(site), fetcher)

    async with db.session() as session:
        feeds = len((await session.execute(select(Feed.id))).scalars().all())
        subscriptions = len((await session.execute(select(Subscription.id))).scalars().all())

    assert feeds == subscriptions == 2
