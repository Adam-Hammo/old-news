from old_news.api.routes.archive import archive_router
from old_news.api.routes.health import health_router
from old_news.api.routes.reading import reading_router
from old_news.api.routes.reports import reports_router
from old_news.api.routes.subscriptions import subscriptions_router

__all__ = [
    "archive_router",
    "health_router",
    "reading_router",
    "reports_router",
    "subscriptions_router",
]
