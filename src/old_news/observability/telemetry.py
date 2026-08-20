import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from typing import Any

import logfire
from litestar.plugins.opentelemetry import OpenTelemetryConfig
from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.semconv.attributes.http_attributes import HTTP_ROUTE

from old_news import __version__
from old_news.config import TelemetrySettings

_tracer = trace.get_tracer("old_news")
_meter = metrics.get_meter("old_news")

# An interactive UI: every list page and static asset would otherwise be a span.
UNTRACED_PATHS = ["/health", "/schema", "/admin"]

SENSITIVE_FIELDS = ["password", "passwd", "token", "secret", "authorization", "auth"]

_enabled = False
_instrument_database = False


def configure(settings: TelemetrySettings, *, environment: str, component: str) -> None:
    """Installs the global OTel provider. The rest of the app talks to OTel, not Logfire."""
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

    # Log records carry the active trace id, so a line links to the span it happened in.
    logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

    # Pydantic's plugin decides whether to record when a model builds its validator,
    # which for anything imported at startup happens before this runs — so its switch
    # has to arrive in the environment instead.
    global _enabled, _instrument_database
    _enabled = True
    _instrument_database = settings.instrument_database

    if settings.system_metrics:
        logfire.instrument_system_metrics()


def instrument_engine(engine: Any) -> None:
    """Called by `db.configure` with the engine it just built."""
    if not _instrument_database:
        return
    logfire.instrument_sqlalchemy(engine=engine, skip_dep_check=True)


def instrument_http_client(client: Any) -> None:
    """Called by `Fetcher` with the client it just built. This client only, and no bodies."""
    if not _enabled:
        return
    logfire.instrument_httpx(client)


@dataclass(frozen=True)
class _Route:
    """What the ASGI instrumentation reads for metrics, which Litestar does not set."""

    path_format: str


def _span_details(scope: Any) -> tuple[str, dict[str, str]]:
    """The name a span is born with, before routing has happened."""
    return str(scope.get("method", "")).strip() or "HTTP", {}


async def name_span_after_route(request: Any) -> None:
    """Litestar `before_request` hook: the first point at which the route is known."""
    template = str(request.scope.get("path_template") or "").strip()
    if not template:
        return

    request.scope["route"] = _Route(path_format=template)

    span = trace.get_current_span()
    if span.is_recording():
        span.update_name(f"{request.method} {template}")
        span.set_attribute(HTTP_ROUTE, template)


def litestar_config() -> OpenTelemetryConfig:
    return OpenTelemetryConfig(
        scope_span_details_extractor=_span_details,
        exclude_spans=["receive", "send"],
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
