"""Credentials must not reach the telemetry backend.

Logfire treats `http.url` as safe and never scrubs it, and the attribute keeps the
whole query string — so for a route that can carry a credential the only defence is
not tracing it. That is what UNTRACED_PATHS is for.
"""

from pathlib import Path

import pytest
from litestar import Litestar, get
from litestar.handlers import HTTPRouteHandler
from litestar.params import FromPath
from litestar.plugins.opentelemetry import OpenTelemetryPlugin
from litestar.testing import TestClient
from logfire.testing import CaptureLogfire, TestExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan

from old_news.observability import telemetry
from old_news.observability.telemetry import litestar_config, name_span_after_route

SECRET = "hunter2-SUPERSECRET"
TOKEN = "adam/DEADBEEFTOKEN"


@get("/admin/login")
async def admin_login() -> dict[str, bool]:
    return {"ok": True}


@get("/traced")
async def traced() -> dict[str, bool]:
    return {"ok": True}


APP_MODULE = Path(telemetry.__file__).resolve().parents[1] / "api" / "app.py"


@pytest.fixture
def exporter(capfire: CaptureLogfire) -> TestExporter:
    return capfire.exporter


@pytest.fixture
def reader(capfire: CaptureLogfire) -> InMemoryMetricReader:
    return capfire.metrics_reader


def _app(*handlers: HTTPRouteHandler) -> Litestar:
    """Wired the way `create_app` wires it — the hook is half of the behaviour."""
    return Litestar(
        route_handlers=list(handlers),
        plugins=[OpenTelemetryPlugin(litestar_config())],
        before_request=name_span_after_route,
    )


@get("/feeds/{feed_id:int}/articles/{slug:str}")
async def article(feed_id: FromPath[int], slug: FromPath[str]) -> dict[str, bool]:
    return {"ok": True}


def _finished(exporter: TestExporter) -> list[ReadableSpan]:
    """Logfire emits a pending span at the start; the finished one is the span that matters."""
    return [
        span
        for span in exporter.exported_spans
        if (span.attributes or {}).get("logfire.span_type") != "pending_span"
    ]


def _duration_series(reader: InMemoryMetricReader) -> list[dict[str, object]]:
    data = reader.get_metrics_data()
    return [
        dict(point.attributes or {})
        for resource in (data.resource_metrics if data else [])
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if "http.server" in metric.name and "duration" in metric.name
        for point in metric.data.data_points
    ]


def _emitted(exporter: TestExporter) -> str:
    return "\n".join(
        f"{key}={value}"
        for span in exporter.exported_spans
        for key, value in (span.attributes or {}).items()
    )


def test_credentials_in_the_query_string_are_never_traced(exporter: TestExporter):
    app = Litestar(route_handlers=[admin_login], plugins=[OpenTelemetryPlugin(litestar_config())])

    with TestClient(app=app) as client:
        client.get(f"/admin/login?username=adam&password={SECRET}")

    assert SECRET not in _emitted(exporter)


def test_authorization_header_is_never_captured(exporter: TestExporter):
    app = Litestar(route_handlers=[traced], plugins=[OpenTelemetryPlugin(litestar_config())])

    with TestClient(app=app) as client:
        client.get("/traced", headers={"Authorization": f"GoogleLogin auth={TOKEN}"})

    assert TOKEN not in _emitted(exporter)


def test_ordinary_routes_are_still_traced(exporter: TestExporter):
    """Guards against fixing the leak by turning tracing off entirely."""
    app = Litestar(route_handlers=[traced], plugins=[OpenTelemetryPlugin(litestar_config())])

    with TestClient(app=app) as client:
        client.get("/traced")

    assert any("/traced" in str(span.attributes) for span in exporter.exported_spans)


def test_span_names_use_the_route_not_the_path(exporter: TestExporter):
    """One span name per route. Litestar's own extractor returns `GET /feeds/1`, so
    an id in a path becomes a distinct span name for every id ever requested."""
    with TestClient(app=_app(article)) as client:
        for feed_id in (1, 2, 3):
            client.get(f"/feeds/{feed_id}/articles/post-{feed_id}")

    assert {span.name for span in _finished(exporter)} == {"GET /feeds/{feed_id}/articles/{slug}"}


def test_the_route_attribute_is_the_template_without_the_method(exporter: TestExporter):
    with TestClient(app=_app(article)) as client:
        client.get("/feeds/7/articles/anything")

    routes = {(span.attributes or {}).get("http.route") for span in _finished(exporter)}
    assert routes == {"/feeds/{feed_id}/articles/{slug}"}


def test_many_urls_share_one_duration_series(reader: InMemoryMetricReader):
    """The point of the whole exercise: unbounded metric series as traffic grows."""
    with TestClient(app=_app(article)) as client:
        for feed_id in range(5):
            client.get(f"/feeds/{feed_id}/articles/post-{feed_id}")

    series = _duration_series(reader)
    assert len(series) == 1
    assert series[0]["http.target"] == "/feeds/{feed_id}/articles/{slug}"


def test_an_unmatched_path_is_not_given_a_name_of_its_own(exporter: TestExporter):
    """Otherwise one scanner walking a wordlist is thousands of span names."""
    with TestClient(app=_app(article)) as client:
        client.get("/wp-admin/setup-config.php")
        client.get("/.env")

    assert {span.name for span in _finished(exporter)} == {"GET"}


def test_asgi_plumbing_spans_are_excluded(exporter: TestExporter):
    """`receive` and `send` are three spans per request about ASGI, not the app."""
    with TestClient(app=_app(article)) as client:
        client.get("/feeds/1/articles/x")

    assert not [span for span in _finished(exporter) if "http send" in span.name]


def test_create_app_installs_the_hook():
    """The middleware runs outside the router, so without this the span keeps the
    name it was born with and nothing fails."""
    assert "before_request=observability.name_span_after_route" in APP_MODULE.read_text()
