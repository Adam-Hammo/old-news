from pydantic import BaseModel


class RetrySettings(BaseModel):
    """The bounds one kind of retry moves within. The arithmetic is in `politeness.backoff`."""

    minimum_seconds: int
    maximum_seconds: int
    factor: float
    max_failures: int
