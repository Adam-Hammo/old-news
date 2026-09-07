from pydantic import BaseModel


class TelemetrySettings(BaseModel):
    enabled: bool = False
    service_name: str = "old-news"
    logfire_token: str | None = None
    console: bool = False
    system_metrics: bool = False

    # One span per query turns a 2-span job into a 10-span one. Priceless when
    # chasing a slow query, pure volume the rest of the time.
    instrument_database: bool = False

    # What share of the traces that went neither wrong nor slow is kept. Counters are
    # metrics and are never sampled, so this thins the detail, not the arithmetic.
    background_sample_rate: float = 1.0
    slow_after_seconds: float = 5.0
