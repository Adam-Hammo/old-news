"""Schema bootstrap, safe to run on every boot.

Piccolo's migrations are already idempotent. `procrastinate schema --apply` is not —
it fails with "type procrastinate_job_status already exists" on a second run, which
would break every restart — so it only runs when the queue tables are absent.

Upgrading procrastinate itself is a separate job: its versioned migration scripts
live at `procrastinate schema --migrations-path` and are applied by hand.
"""

import asyncio

from piccolo.apps.migrations.commands.forwards import run_forwards

from old_news.db import DB, run_sql
from old_news.tasks import app as queue_app


async def queue_schema_installed() -> bool:
    rows = await run_sql("SELECT to_regclass('procrastinate_jobs') AS table_name")
    return rows[0]["table_name"] is not None


async def migrate() -> None:
    await DB.start_connection_pool()
    try:
        await run_forwards("all")
        installed = await queue_schema_installed()
    finally:
        await DB.close_connection_pool()

    if installed:
        print("procrastinate schema already present")
        return

    async with queue_app.open_async():
        await queue_app.schema_manager.apply_schema_async()
    print("procrastinate schema applied")


def main() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
