"""Where a river page stopped, as one opaque string. Keyset, so a new item skips nothing."""

import base64
import binascii
import datetime
import uuid

SEPARATOR = "|"


class BadCursor(ValueError):
    """Handed something that was not one of ours."""


def encode(seen: datetime.datetime, item_id: uuid.UUID) -> str:
    raw = f"{seen.isoformat()}{SEPARATOR}{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor: str) -> tuple[datetime.datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        seen, _, item_id = base64.urlsafe_b64decode(padded).decode().partition(SEPARATOR)
        return datetime.datetime.fromisoformat(seen), uuid.UUID(item_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise BadCursor(cursor) from exc
