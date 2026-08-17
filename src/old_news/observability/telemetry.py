import logging
from collections.abc import Generator
from contextlib import contextmanager
from functools import cache
from typing import Any

import logfire
from litestar.plugins.opentelemetry import OpenTelemetryConfig
from opentelemetry import metrics, trace
from opentelemetry.context import Context

from old_news import __version__
from old_news.config import TelemetrySettings

_tracer = trace.get_tracer("old_news")
_meter = metrics.get_meter("old_news")

# /admin is an interactive UI: every list page and static asset would be a
# span, for a surface that is not part of the product.
UNTRACED_PATHS = ["/health", "/schema", "/admin"]

SENSITIVE_FIELDS = ["password", "passwd", "token", "secret", "authorization", "auth"]

_instrument_database = False


def configure(settings: TelemetrySettings, *, environment: str, component: str) -> None:
    """Installs the global OTel provider. The rest of the app talks to OTel, not Logfire.

    One service name for both the API and the worker collapses them into a single
    stream, so `component` names the process.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s"
    )

    if not settings.enabled:
        return

    logfire.configure(
        service_name=f"{settings.service_name}-{component}",
        service_version=__version__,
        environment=environment,
        token=settings.logfire_token,
        console=logfire.ConsoleOptions() if settings.console else False,
        send_to_logfire="if-token-present",
        scrubbing=logfire.ScrubbingOptions(extra_patterns=SENSITIVE_FIELDS),
    )

    # Log records carry the active trace id, so a log line links to the span it
    # happened in rather than sitting in a separate stream.
    logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

    # Not instrumented here: db.configure hands the engine to instrument_engine.
    global _instrument_database
    _instrument_database = settings.instrument_database

    if settings.system_metrics:
        logfire.instrument_system_metrics()


def instrument_engine(engine: Any) -> None:
    """Called by `db.configure` with the engine it just built."""
    if not _instrument_database:
        return
    logfire.instrument_sqlalchemy(engine=engine, skip_dep_check=True)


def litestar_config() -> OpenTelemetryConfig:
    return OpenTelemetryConfig(
        exclude=UNTRACED_PATHS,
        http_capture_headers_server_request=["content-type", "user-agent"],
        http_capture_headers_server_response=["content-type"],
        http_capture_headers_sanitize_fields=SENSITIVE_FIELDS,
    )


@contextmanager
def span(
    name: str, /, *, context: Context | None = None, **attributes: Any
) -> Generator[trace.Span]:
    with _tracer.start_as_current_span(name, context=context, attributes=attributes) as current:
        yield current


@cache
def _counter(name: str, unit: str, description: str) -> metrics.Counter:
    return _meter.create_counter(name, unit=unit, description=description)


@cache
def _gauge(name: str, unit: str, description: str) -> metrics._Gauge:
    return _meter.create_gauge(name, unit=unit, description=description)


def count(name: str, /, amount: int = 1, *, unit: str = "1", **attributes: Any) -> None:
    _counter(name, unit, "").add(amount, attributes)


def gauge(name: str, value: float, /, *, unit: str = "1", **attributes: Any) -> None:
    _gauge(name, unit, "").set(value, attributes)
