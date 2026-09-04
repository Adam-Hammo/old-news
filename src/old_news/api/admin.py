"""Never publicly reachable — full CRUD over the archive."""

import logging
from hmac import compare_digest
from typing import cast

from litestar.types import ASGIApp, Receive, Scope, Send
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from old_news import passwords
from old_news.config import AdminSettings
from old_news.config.admin import DEVELOPMENT_PASSWORD
from old_news.db import (
    Document,
    Extraction,
    Feed,
    FeedCapture,
    FeedPoll,
    ImageCapture,
    Issue,
    IssueItem,
    Item,
    ItemVersion,
    PageCapture,
    PageExtraction,
    Subscription,
    TrainingRule,
)

logger = logging.getLogger(__name__)


class SingleUserBackend(AuthenticationBackend):
    """One seeded credential, from config. No registration endpoint, ever."""

    def __init__(self, settings: AdminSettings) -> None:
        super().__init__(secret_key=settings.session_secret.get_secret_value())
        self._username = settings.username
        self._hash = settings.password_hash.get_secret_value()

        if not self._hash:
            logger.warning(
                "admin has no password hash; falling back to the development "
                "password. Run `just admin-password` and set "
                "OLD_NEWS_ADMIN__PASSWORD_HASH."
            )
            self._hash = passwords.hash_password(DEVELOPMENT_PASSWORD)

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username, password = str(form.get("username", "")), str(form.get("password", ""))

        # Both halves always compared, so timing cannot confirm a username. Bytes, not
        # str: compare_digest raises TypeError on non-ASCII text.
        named = compare_digest(username.encode(), self._username.encode())
        known = passwords.verify(password, self._hash)
        if not (named and known):
            return False

        request.session.update({"user": username})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> Response | bool:
        if request.session.get("user"):
            return True
        return RedirectResponse(request.url_for("admin:login"), status_code=302)


class MachineWritten:
    """Written by a sweep, not by hand."""

    can_create = False
    can_edit = False


class FeedAdmin(ModelView, model=Feed):
    icon = "fa-solid fa-rss"
    # Failure state is derived from `feed_polls`, so there is no column to list or sort on.
    column_list = [Feed.title, Feed.url, Feed.next_poll_at, Feed.last_polled_at]
    column_searchable_list = [Feed.title, Feed.url]
    column_sortable_list = [Feed.title, Feed.next_poll_at, Feed.last_polled_at]
    column_default_sort = [(Feed.next_poll_at, False)]


class FeedPollAdmin(MachineWritten, ModelView, model=FeedPoll):
    name = "Feed poll"
    icon = "fa-solid fa-clock-rotate-left"
    column_list = [
        FeedPoll.polled_at,
        FeedPoll.outcome,
        FeedPoll.status,
        FeedPoll.new_items,
        FeedPoll.error,
    ]
    column_sortable_list = [FeedPoll.polled_at, FeedPoll.outcome, FeedPoll.status]
    column_default_sort = [(FeedPoll.polled_at, True)]
    can_delete = False


class SubscriptionAdmin(ModelView, model=Subscription):
    icon = "fa-solid fa-star"
    # Where the window and the tier are set. Both are taste, and this is the screen
    # the roadmap already gives per-feed choices.
    column_list = [
        Subscription.category,
        Subscription.active,
        Subscription.expires_after,
        Subscription.tier,
        Subscription.added_at,
    ]
    column_sortable_list = [
        Subscription.category,
        Subscription.expires_after,
        Subscription.tier,
        Subscription.added_at,
    ]


class IssueAdmin(MachineWritten, ModelView, model=Issue):
    icon = "fa-solid fa-newspaper"
    # Not `body`: the bytes are kept for a resend, not for reading in a browser.
    column_list = [Issue.built_at, Issue.title, Issue.byte_size, Issue.sent_at, Issue.error]
    column_sortable_list = [Issue.built_at, Issue.sent_at, Issue.byte_size]
    column_default_sort = [(Issue.built_at, True)]


class IssueItemAdmin(MachineWritten, ModelView, model=IssueItem):
    name = "Issue article"
    icon = "fa-solid fa-list-ol"
    column_list = [IssueItem.issue_id, IssueItem.section, IssueItem.position, IssueItem.item_id]
    column_sortable_list = [IssueItem.section, IssueItem.position]


class ItemAdmin(ModelView, model=Item):
    icon = "fa-solid fa-fingerprint"
    # Identity only; the content lives on the versions.
    column_list = [
        Item.id,
        Item.identity_key,
        Item.identity_source,
        Item.first_seen_at,
        Item.read,
        Item.finished_at,
    ]
    column_sortable_list = [Item.first_seen_at]
    column_default_sort = [(Item.first_seen_at, True)]


class ItemVersionAdmin(MachineWritten, ModelView, model=ItemVersion):
    name = "Item version"
    icon = "fa-solid fa-clock-rotate-left"
    column_list = [
        ItemVersion.title,
        ItemVersion.observed_at,
        ItemVersion.supersedes_id,
        ItemVersion.canonical_url,
        ItemVersion.published_at,
    ]
    column_searchable_list = [ItemVersion.title, ItemVersion.canonical_url]
    column_sortable_list = [ItemVersion.observed_at, ItemVersion.published_at]
    column_default_sort = [(ItemVersion.observed_at, True)]
    can_delete = False


class DocumentAdmin(MachineWritten, ModelView, model=Document):
    icon = "fa-solid fa-file-code"
    # `body` is a compressed document, and listing fifty of them makes the page unusable.
    column_list = [Document.fetched_at, Document.status, Document.parse_ok, Document.parse_note]
    column_sortable_list = [Document.fetched_at, Document.status]
    column_default_sort = [(Document.fetched_at, True)]


class PageCaptureAdmin(MachineWritten, ModelView, model=PageCapture):
    name = "Page capture"
    icon = "fa-solid fa-file-arrow-down"
    column_list = [
        PageCapture.fetched_at,
        PageCapture.status,
        PageCapture.url,
        PageCapture.final_url,
        PageCapture.error,
    ]
    column_searchable_list = [PageCapture.url]
    column_sortable_list = [PageCapture.fetched_at, PageCapture.status]
    column_default_sort = [(PageCapture.fetched_at, True)]


class FeedCaptureAdmin(MachineWritten, ModelView, model=FeedCapture):
    name = "Feed capture"
    icon = "fa-solid fa-scissors"
    column_list = [
        FeedCapture.captured_at,
        FeedCapture.parser_version,
        FeedCapture.item_version_id,
        FeedCapture.document_id,
    ]
    column_sortable_list = [FeedCapture.captured_at, FeedCapture.parser_version]
    column_default_sort = [(FeedCapture.captured_at, True)]


class ExtractionAdmin(MachineWritten, ModelView, model=Extraction):
    icon = "fa-solid fa-align-left"
    # The measurements. Whether a row passes is a threshold in config, so not a column.
    column_list = [
        Extraction.source,
        Extraction.char_count,
        Extraction.paragraph_count,
        Extraction.link_density,
        Extraction.extractor_version,
        Extraction.created_at,
    ]
    column_sortable_list = [
        Extraction.source,
        Extraction.char_count,
        Extraction.link_density,
        Extraction.created_at,
    ]
    column_default_sort = [(Extraction.char_count, False)]


class PageExtractionAdmin(MachineWritten, ModelView, model=PageExtraction):
    name = "Page extraction"
    icon = "fa-solid fa-newspaper"
    # What a page claimed about itself, kept beside what the feed said rather than merged.
    column_list = [
        PageExtraction.title,
        PageExtraction.byline,
        PageExtraction.site_name,
        PageExtraction.published_claim,
        PageExtraction.char_count,
        PageExtraction.extractor_version,
    ]
    column_searchable_list = [PageExtraction.title, PageExtraction.site_name]
    column_sortable_list = [PageExtraction.title, PageExtraction.char_count]


class ImageCaptureAdmin(MachineWritten, ModelView, model=ImageCapture):
    name = "Image capture"
    icon = "fa-solid fa-image"
    # `byte_size` is why images are held to one per article.
    column_list = [
        ImageCapture.fetched_at,
        ImageCapture.status,
        ImageCapture.byte_size,
        ImageCapture.content_type,
        ImageCapture.spec,
        ImageCapture.url,
        ImageCapture.error,
    ]
    column_searchable_list = [ImageCapture.url]
    column_sortable_list = [ImageCapture.byte_size, ImageCapture.fetched_at]
    column_default_sort = [(ImageCapture.byte_size, True)]


class TrainingRuleAdmin(ModelView, model=TrainingRule):
    name = "Training rule"
    icon = "fa-solid fa-filter"
    # Full CRUD: these are hand-made and unrecoverable. A rule with no feed is global.
    column_list = [
        TrainingRule.dimension,
        TrainingRule.pattern,
        TrainingRule.blocks,
        TrainingRule.feed_id,
        TrainingRule.source,
        TrainingRule.note,
    ]
    column_searchable_list = [TrainingRule.pattern, TrainingRule.note]
    column_sortable_list = [TrainingRule.dimension, TrainingRule.created_at]
    column_default_sort = [(TrainingRule.created_at, True)]


def create_admin(engine: AsyncEngine, settings: AdminSettings) -> ASGIApp:
    """sqladmin is a Starlette app; Litestar mounts it as a plain ASGI sub-application."""
    host = Starlette()
    admin = Admin(
        app=host,
        engine=engine,
        base_url="/",
        title="old-news",
        authentication_backend=SingleUserBackend(settings),
    )
    views = (
        FeedAdmin,
        FeedPollAdmin,
        SubscriptionAdmin,
        IssueAdmin,
        IssueItemAdmin,
        ItemAdmin,
        ItemVersionAdmin,
        DocumentAdmin,
        PageCaptureAdmin,
        FeedCaptureAdmin,
        ExtractionAdmin,
        PageExtractionAdmin,
        ImageCaptureAdmin,
        TrainingRuleAdmin,
    )
    for view in views:
        admin.add_view(view)

    # The only place Litestar's and Starlette's ASGI types meet.
    downstream = cast("ASGIApp", host)

    async def mounted(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            # Litestar strips the mount prefix from `path` and leaves `root_path` empty;
            # Starlette derives its route by subtracting one from the other, so it needs
            # `path` whole. Restoring both is what keeps nested Mounts — the statics —
            # routing. Litestar also appends a trailing slash sqladmin's routes lack.
            trimmed = scope["path"].rstrip("/") or "/"
            forwarded = {
                **scope,
                "root_path": settings.path,
                "path": settings.path + trimmed,
            }
            forwarded.pop("raw_path", None)
            scope = cast("Scope", forwarded)
        await downstream(scope, receive, send)

    return mounted
