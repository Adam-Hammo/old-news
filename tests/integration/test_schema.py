from old_news.db import DB, run_sql
from old_news.db.migrate import migrate, queue_schema_installed
from old_news.tasks.maintenance import heartbeat

# Anything beyond these ends up in every pg_dump and is then needed to restore.
EXPECTED_EXTENSIONS = {"plpgsql", "vector", "vectorscale", "pg_search"}


async def test_extension_set_is_exactly_what_we_asked_for(database: None):
    rows = await run_sql("SELECT extname FROM pg_extension")
    installed = {row["extname"] for row in rows}

    assert installed == EXPECTED_EXTENSIONS


async def test_procrastinate_schema_is_applied(database: None):
    rows = await run_sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = {row["tablename"] for row in rows}

    assert {"procrastinate_jobs", "procrastinate_events"} <= tables


async def test_autotuning_ran(database: None):
    rows = await run_sql("SELECT setting FROM pg_settings WHERE name = 'shared_buffers'")

    # Postgres reports this in 8kB blocks; the default is 16384 (128MB).
    assert int(rows[0]["setting"]) > 16384


async def test_migrate_is_idempotent(migrated: None):
    """Every `docker compose up` runs this, and procrastinate's own apply is not re-runnable.

    Takes `migrated` rather than `database`: migrate() opens its own pool.
    """
    await migrate()
    await migrate()

    await DB.start_connection_pool()
    try:
        assert await queue_schema_installed()
    finally:
        await DB.close_connection_pool()


async def test_both_engines_share_the_container_database(database: None, queue_app):
    """Piccolo and procrastinate are configured independently — procrastinate reads
    OLD_NEWS_DATABASE__URL at import. If they ever point at different databases the
    suite passes while testing a developer's machine.
    """
    async with queue_app.open_async():
        await heartbeat.defer_async(note="same-database")

    rows = await run_sql(
        "SELECT count(*) AS n FROM procrastinate_jobs WHERE task_name = 'heartbeat'"
    )

    assert rows[0]["n"] > 0
