from pydantic import BaseModel


class HttpSettings(BaseModel):
    user_agent: str = "old-news/0.1 (+https://github.com/Adam-Hammo/old-news)"
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_body_bytes: int = 16 * 1024 * 1024
