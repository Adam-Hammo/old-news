"""A shared Fetcher client."""

from old_news.config.http import HttpSettings
from old_news.fetch.client import Fetcher

_settings: HttpSettings | None = None
_client: Fetcher | None = None


def configure(settings: HttpSettings) -> None:
    """Safe to call outside a running loop; nothing is built until `client()`."""
    global _settings, _client
    _settings = settings
    _client = None


def client() -> Fetcher:
    if _settings is None:
        raise RuntimeError("http client not configured; call fetch.configure() first")

    global _client
    if _client is None:
        _client = Fetcher(_settings)
    return _client


async def dispose() -> None:
    global _settings, _client
    if _client is not None:
        await _client.aclose()
    _settings = None
    _client = None
