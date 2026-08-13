from urllib.parse import unquote, urlparse

from pydantic import BaseModel


class DatabaseSettings(BaseModel):
    url: str = "postgres://old_news:old_news@localhost:5432/old_news"
    pool_max_size: int = 10
    log_queries: bool = False

    def asyncpg_kwargs(self) -> dict[str, object]:
        parts = urlparse(self.url)
        return {
            "database": parts.path.lstrip("/") or "old_news",
            "user": unquote(parts.username or "old_news"),
            "password": unquote(parts.password or ""),
            "host": parts.hostname or "localhost",
            "port": parts.port or 5432,
        }

    @property
    def psycopg_url(self) -> str:
        return self.url.replace("postgres://", "postgresql://", 1)
