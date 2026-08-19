from pydantic import BaseModel


class RetrySettings(BaseModel):
    """The bounds one kind of retry moves within. Mirrors `politeness.backoff.Policy`,
    which is where the arithmetic lives."""

    minimum_seconds: int
    maximum_seconds: int
    factor: float
    max_failures: int
