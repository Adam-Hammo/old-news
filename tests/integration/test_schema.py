from sqlalchemy import text

from old_news import db
from old_news.config import Settings
from old_news.db.migrate import queue_schema_installed, upgrade
from old_news.tasks.maintenance import heartbeat

# Anything beyond these ends up in every pg_dump and is then needed to restore.
EXPECTED_EXTENSIONS = {"plpgsql", "vector", "vectorscale", "pg_search"}


async def _scalars(sql: str) -> list:
    async with db.session() as session:
        return list((await session.execute(text(sql))).scalars().all())


async def test_extension_set_is_exactly_what_we_asked_for(database: None):
    assert set(await _scalars("SELECT extname FROM pg_extension")) == EXPECTED_EXTENSIONS


async def test_procrastinate_schema_is_applied(database: None, queue_schema: None):
    tables = set(await _scalars("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))

    assert {"procrastinate_jobs", "procrastinate_events"} <= tables


async def test_autotuning_ran(database: None):
    rows = await _scalars("SELECT setting FROM pg_settings WHERE name = 'shared_buffers'")

    # Postgres reports this in 8kB blocks; the default is 16384 (128MB).
    assert int(rows[0]) > 16384


def test_upgrade_is_idempotent(migrated: None, settings: Settings):
    """Every `docker compose up` runs this. Alembic's env.py drives its own loop,
    so this test stays synchronous."""
    upgrade(settings.database.sqlalchemy_url)
    upgrade(settings.database.sqlalchemy_url)


async def test_queue_schema_reports_installed(database: None, queue_schema: None):
    assert await queue_schema_installed()


async def test_both_clients_share_the_container_database(
    database: None, queue_schema: None, queue_app
):
    """SQLAlchemy and procrastinate are configured independently, and procrastinate
    reads OLD_NEWS_DATABASE__URL at import. If they ever point at different
    databases the suite passes while testing a developer's machine.
    """
    async with queue_app.open_async():
        await heartbeat.defer_async(note="same-database")

    rows = await _scalars("SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'heartbeat'")

    assert rows[0] > 0
