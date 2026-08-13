from typing import Any

from piccolo.querystring import QueryString

from old_news.db.piccolo_conf import DB


async def run_sql(sql: str, *args: Any) -> list[dict[str, Any]]:
    """Escape hatch for the DDL Piccolo can't model — partitions, BM25 indexes, vectors."""
    return await DB.run_querystring(QueryString(sql, *args))


__all__ = ["DB", "run_sql"]
