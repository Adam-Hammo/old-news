from piccolo.conf.apps import AppRegistry
from piccolo.engine.postgres import PostgresEngine

from old_news.config import get_settings

_database = get_settings().database

# Pool sizing is a create_pool() kwarg, not a connect() one — it goes to
# start_connection_pool(), not in here.
DB = PostgresEngine(
    config=_database.asyncpg_kwargs(),
    log_queries=_database.log_queries,
)

APP_REGISTRY = AppRegistry(apps=["old_news.db.piccolo_app"])
