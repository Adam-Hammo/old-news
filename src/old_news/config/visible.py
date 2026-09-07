"""Every effective setting, with nothing that could log anybody in."""

import dataclasses
from typing import Any

from pydantic import BaseModel, SecretStr

from old_news.config import Settings

REDACTED = "—"

# Belt and braces. `SecretStr` renders itself as asterisks and every credential is one,
# but a field added as a plain `str` would not be, and the cost of being wrong is a
# credential on a screen.
SENSITIVE = ("password", "passwd", "token", "secret", "url", "hash", "dsn")


@dataclasses.dataclass(frozen=True, slots=True)
class Setting:
    """One setting, rendered. A string, so the shape does not change with the type."""

    name: str
    value: str


@dataclasses.dataclass(frozen=True, slots=True)
class Section:
    name: str
    settings: tuple[Setting, ...]


def _secret(name: str, value: Any) -> bool:
    return isinstance(value, SecretStr) or any(word in name.lower() for word in SENSITIVE)


def _rendered(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, tuple | list):
        return ", ".join(str(each) for each in value) or REDACTED
    return str(value) if value != "" and value is not None else REDACTED


def _section(name: str, model: BaseModel) -> Section:
    return Section(
        name=name,
        settings=tuple(
            Setting(name=field, value=REDACTED if _secret(field, value) else _rendered(value))
            for field, value in model
        ),
    )


def sections(settings: Settings | None = None) -> tuple[Section, ...]:
    """What the settings screen shows. Everything, so a new setting appears on its own."""
    current = settings or Settings()
    return tuple(
        _section(name, value)
        for name, value in current
        if isinstance(value, BaseModel) and not isinstance(value, Settings)
    )
