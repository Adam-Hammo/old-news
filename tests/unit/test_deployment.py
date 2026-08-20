"""The deployment must invoke our entrypoints, not the libraries' own.

`procrastinate --app=… worker` starts a worker that never calls db.configure(),
so every task raises on its first statement. The bug is invisible in tests —
fixtures configure an engine — and only shows up in a deployed process, so the
guard is on the command the deployment actually runs.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUR_WORKER = "python -m old_news worker"
OUR_API = 'python", "-m", "old_news", "serve'
BARE_UVICORN = "uvicorn"
# `procrastinate --app=… healthchecks` is fine — it uses procrastinate's own
# connection. Only running the *worker* that way is the bug.
BARE_WORKER = "procrastinate --app=old_news.tasks.app worker"


def test_compose_runs_our_worker_entrypoint():
    compose = (REPO / "compose.yaml").read_text()

    assert OUR_WORKER in compose
    assert BARE_WORKER not in compose


def test_the_justfile_runs_our_worker_entrypoint():
    justfile = (REPO / "justfile").read_text()

    assert OUR_WORKER in justfile
    assert BARE_WORKER not in justfile


def test_the_image_runs_our_api_entrypoint():
    """Running uvicorn by hand loses every setting the entrypoint reads — including
    forwarded_allow_ips, without which TLS-terminated-upstream generates http://
    URLs and the browser blocks the page's own assets."""
    dockerfile = (REPO / "Dockerfile").read_text()

    assert OUR_API in dockerfile
    assert f'CMD ["{BARE_UVICORN}"' not in dockerfile


def test_compose_sets_the_pydantic_plugin_record_level():
    """Pydantic asks the plugin whether to record when a model builds its validator.
    Every model imported at startup is built before the app can call anything, so
    `logfire.instrument_pydantic()` would be too late for all of them and silently
    do nothing. The environment is the only thing early enough."""
    compose = (REPO / "compose.yaml").read_text()

    assert "LOGFIRE_PYDANTIC_PLUGIN_RECORD" in compose
    assert (
        "instrument_pydantic(" not in (REPO / "src/old_news/observability/telemetry.py").read_text()
    )


ALERTS_FILE = REPO / "infra" / "resources" / "telemetry_logfire.py"
# `%` is the SQL wildcard, and a format placeholder is whatever the argument was.
LOG_MESSAGE = re.compile(r"message like '([^']+)'")


def _alert_message_prefixes() -> list[str]:
    """The literal text each message-matching alert waits for."""
    return [
        match.strip("%") for match in LOG_MESSAGE.findall(ALERTS_FILE.read_text()) if match != "%"
    ]


def test_every_alert_matches_a_message_the_code_still_logs():
    """An alert is a string in one repo matching a string in another, and renaming the
    log line breaks it in total silence — which is the one thing an alert must not do.
    `feed-given-up` was `suspending feed%` until the log line changed underneath it."""
    logged = "\n".join(
        path.read_text() for path in (REPO / "src").rglob("*.py") if "migrations" not in path.parts
    )
    prefixes = _alert_message_prefixes()

    assert prefixes, "no message-matching alerts found — has the query syntax changed?"
    missing = [prefix for prefix in prefixes if prefix not in logged]

    assert not missing, f"{missing} are alerted on but no longer logged anywhere in src/"


def test_alerts_only_watch_spans_the_code_emits():
    """Same failure, one layer up: a span rename would silence `ingest-silent` and
    `captures-failing` the same way."""
    source = "\n".join(
        path.read_text() for path in (REPO / "src").rglob("*.py") if "migrations" not in path.parts
    )
    watched = set(re.findall(r"span_name = '([^']+)'", ALERTS_FILE.read_text()))

    assert watched, "no span-matching alerts found"
    missing = [name for name in watched if f'"{name}"' not in source]

    assert not missing, f"{missing} are alerted on but no span is opened with that name"
