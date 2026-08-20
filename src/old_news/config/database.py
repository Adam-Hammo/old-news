import re

from pydantic import BaseModel, SecretStr

_SCHEME = re.compile(r"^[a-z0-9+]+://", re.IGNORECASE)


class DatabaseSettings(BaseModel):
    url: SecretStr = SecretStr("postgres://old_news:old_news@localhost:5432/old_news")
    pool_max_size: int = 10
    log_queries: bool = False

    def _with_scheme(self, scheme: str) -> str:
        return _SCHEME.sub(f"{scheme}://", self.url.get_secret_value(), count=1)

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy names its driver in the scheme; everything else uses plain URLs."""
        return self._with_scheme("postgresql+asyncpg")

    @property
    def migration_url(self) -> str:
        """Migrations run on a blocking driver. Nothing about them wants a loop."""
        return self._with_scheme("postgresql+psycopg")

    @property
    def psycopg_url(self) -> str:
        return self._with_scheme("postgresql")
