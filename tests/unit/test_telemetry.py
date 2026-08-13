"""Credentials must not reach the telemetry backend.

The Google Reader protocol puts the API password in a query parameter, and the
`http.url` span attribute keeps the whole query string. Logfire treats `http.url` as
a SAFE_KEY and never scrubs it, so the only defence is not tracing the route.
"""

import logfire
import pytest
from litestar import Litestar, get
from litestar.plugins.opentelemetry import OpenTelemetryPlugin
from litestar.testing import TestClient
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from old_news.observability.telemetry import litestar_config

SECRET = "hunter2-SUPERSECRET"
TOKEN = "adam/DEADBEEFTOKEN"


@get("/accounts/ClientLogin")
async def client_login() -> dict[str, bool]:
    return {"ok": True}


@get("/traced")
async def traced() -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture
def exporter() -> TestExporter:
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )
    return exporter


def _emitted(exporter: TestExporter) -> str:
    return "\n".join(
        f"{key}={value}"
        for span in exporter.exported_spans
        for key, value in (span.attributes or {}).items()
    )


def test_credentials_in_the_query_string_are_never_traced(exporter: TestExporter):
    app = Litestar(route_handlers=[client_login], plugins=[OpenTelemetryPlugin(litestar_config())])

    with TestClient(app=app) as client:
        client.get(f"/accounts/ClientLogin?Email=adam&Passwd={SECRET}")

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
