"""Where a river page stopped, as one opaque string. Keyset, so a new item skips nothing."""

import base64
import binascii
import datetime
import uuid

SEPARATOR = "|"


class BadCursor(ValueError):
    """Handed something that was not one of ours."""


def encode(first: datetime.datetime, second: datetime.datetime, item_id: uuid.UUID) -> str:
    """The sort keys of the last row on a page, in the order that list is sorted by."""
    raw = SEPARATOR.join((first.isoformat(), second.isoformat(), str(item_id))).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime.datetime, datetime.datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        first, second, item_id = base64.urlsafe_b64decode(padded).decode().split(SEPARATOR)
        return (
            datetime.datetime.fromisoformat(first),
            datetime.datetime.fromisoformat(second),
            uuid.UUID(item_id),
        )
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise BadCursor(cursor) from exc
