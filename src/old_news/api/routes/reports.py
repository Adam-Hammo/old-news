"""What the reading UI could not recover from. A phone has nowhere else to say it."""

import dataclasses
import logging

from litestar import Router, post

logger = logging.getLogger(__name__)

# A client in a loop must not be able to write unbounded log lines.
MESSAGE_CHARS = 600


@dataclasses.dataclass(frozen=True, slots=True)
class Report:
    """One thing that went wrong in a browser, and enough about where to place it."""

    kind: str
    message: str
    url: str
    # "standalone" is the home-screen app, which iOS suspends and resumes, against
    # "browser" for a tab. The two fail differently, so a report has to say which.
    display: str
    # Milliseconds since the document was last shown, so a fault on resume reads as one.
    since_visible: int


@post(
    "/client-reports",
    summary="Record something the reading UI could not recover from.",
    status_code=204,
)
async def client_report(data: Report) -> None:
    logger.warning(
        "client %s at %s (%s, %sms since visible): %s",
        data.kind,
        data.url,
        data.display,
        data.since_visible,
        data.message[:MESSAGE_CHARS],
    )


def reports_router(path: str = "/") -> Router:
    return Router(path=path, route_handlers=[client_report], tags=["reports"])
