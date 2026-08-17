"""The deployment must invoke our entrypoints, not the libraries' own.

`procrastinate --app=… worker` starts a worker that never calls db.configure(),
so every task raises on its first statement. The bug is invisible in tests —
fixtures configure an engine — and only shows up in a deployed process, so the
guard is on the command the deployment actually runs.
"""

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
