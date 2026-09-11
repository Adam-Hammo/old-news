"""Where a row sits in the river, and what that number is tied to."""

import datetime

from old_news.config import IngestSettings
from old_news.ui import entries


def test_the_ceiling_tracks_the_backoff():
    """A copy of a setting, so the copy is checked rather than trusted to a comment."""
    backoff = datetime.timedelta(seconds=IngestSettings().max_backoff_seconds)

    assert backoff == entries.SLOWEST_POLL
