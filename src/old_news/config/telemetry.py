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
