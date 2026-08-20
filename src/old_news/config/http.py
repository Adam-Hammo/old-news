from pydantic import BaseModel


class HttpSettings(BaseModel):
    user_agent: str = "old-news/0.1 (+https://github.com/Adam-Hammo/old-news)"
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_body_bytes: int = 16 * 1024 * 1024

    # Floor on the gap between two requests to one host, applied when polls are deferred.
    min_host_interval_seconds: float = 5.0
