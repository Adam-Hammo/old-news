"""Schema bootstrap, safe to run on every boot.

Alembic is idempotent; `procrastinate schema --apply` is not, so it only runs when the
queue tables are absent. Upgrading procrastinate itself is done by hand.
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from old_news import db
from old_news.config import get_settings
from old_news.tasks import app as queue_app


def alembic_config(url: str | None = None) -> Config:
    """Built in code: the image ships the package, so a repo-relative path would not resolve."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url)
    return config


def upgrade(url: str | None = None) -> None:
    """Alembic's env.py runs asyncio.run itself, so this must stay outside a loop."""
    command.upgrade(alembic_config(url), "head")


async def queue_schema_installed() -> bool:
    async with db.session() as session:
        result = await session.execute(text("SELECT to_regclass('procrastinate_jobs')"))
        return result.scalar() is not None


async def apply_queue_schema() -> None:
    db.configure(get_settings().database)
    try:
        installed = await queue_schema_installed()
    finally:
        await db.dispose()

    if installed:
        print("procrastinate schema already present")
        return

    async with queue_app.open_async():
        await queue_app.schema_manager.apply_schema_async()
    print("procrastinate schema applied")


def main() -> None:
    upgrade()
    asyncio.run(apply_queue_schema())


if __name__ == "__main__":
    main()
