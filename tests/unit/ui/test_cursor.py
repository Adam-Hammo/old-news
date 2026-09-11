"""The river's position, there and back."""

import base64
import datetime
import uuid

import pytest

from old_news.ui import cursor


def test_a_position_survives_the_round_trip():
    seen = datetime.datetime(2026, 8, 31, 12, 30, 45, 123456, tzinfo=datetime.UTC)
    dated = datetime.datetime(2026, 8, 30, 9, 15, tzinfo=datetime.UTC)
    item_id = uuid.uuid4()

    assert cursor.decode(cursor.encode(seen, dated, item_id)) == (seen, dated, item_id)


def _v1(first: datetime.datetime, second: datetime.datetime, item_id: uuid.UUID) -> str:
    """What `encode` minted before the ordering moved: the same three fields, no version."""
    raw = "|".join((first.isoformat(), second.isoformat(), str(item_id))).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_a_cursor_from_the_previous_ordering_is_refused():
    """Read against the keys that replaced them it pages from nowhere, so it has to fail loudly."""
    at = datetime.datetime(2026, 8, 31, 12, 30, tzinfo=datetime.UTC)

    with pytest.raises(cursor.BadCursor):
        cursor.decode(_v1(at, at, uuid.uuid4()))


@pytest.mark.parametrize("given", ["", "not-base64!", "Zm9vfGJhcg"])
def test_anything_we_did_not_write_is_refused(given: str):
    with pytest.raises(cursor.BadCursor):
        cursor.decode(given)
