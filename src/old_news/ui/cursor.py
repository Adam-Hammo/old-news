"""Where a river page stopped, as one opaque string. Keyset, so a new item skips nothing."""

import base64
import binascii
import datetime
import uuid

SEPARATOR = "|"


class BadCursor(ValueError):
    """Handed something that was not one of ours."""


def encode(seen: datetime.datetime, dated: datetime.datetime, item_id: uuid.UUID) -> str:
    raw = SEPARATOR.join((seen.isoformat(), dated.isoformat(), str(item_id))).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime.datetime, datetime.datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        seen, dated, item_id = base64.urlsafe_b64decode(padded).decode().split(SEPARATOR)
        return (
            datetime.datetime.fromisoformat(seen),
            datetime.datetime.fromisoformat(dated),
            uuid.UUID(item_id),
        )
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise BadCursor(cursor) from exc
