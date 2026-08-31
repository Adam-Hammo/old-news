"""The river's position, there and back."""

import datetime
import uuid

import pytest

from old_news.ui import cursor


def test_a_position_survives_the_round_trip():
    seen = datetime.datetime(2026, 8, 31, 12, 30, 45, 123456, tzinfo=datetime.UTC)
    item_id = uuid.uuid4()

    assert cursor.decode(cursor.encode(seen, item_id)) == (seen, item_id)


@pytest.mark.parametrize("given", ["", "not-base64!", "Zm9vfGJhcg"])
def test_anything_we_did_not_write_is_refused(given: str):
    with pytest.raises(cursor.BadCursor):
        cursor.decode(given)
