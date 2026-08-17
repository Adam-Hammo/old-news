"""Logfire, minted rather than copied out of the UI so rotation is a `pulumi up`.

The provider is young (0.1.15). If it churns, delete these two resources and hold the
token as secret config instead; nothing else in the stack changes.

Alerts live here for the same reason the tailnet policy does. Dashboards do not:
the provider takes an opaque blob exported from the UI, so those are captured
into `logfire/dashboards/`, not authored.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pulumi
import pulumi_logfire as logfire

DASHBOARDS = Path(__file__).resolve().parent.parent / "logfire" / "dashboards"

# Only production. A laptop running the worker must not be able to fire these.
ENVIRONMENTS = ["production"]


@dataclass(frozen=True)
class Alert:
    slug: str
    name: str
    description: str
    query: str
    time_window: str
    frequency: str
    notify_when: str


ALERTS = (
    Alert(
        slug="ingest-silent",
        name="ingest-silent",
        description="No feed has been polled for an hour. The worker, the box or the deploy.",
        # No "alert when this returns nothing", so silence is inverted into a row:
        # an aggregate with no GROUP BY yields one, HAVING keeps it only at zero.
        query="""
            select count(*) as polls
            from records
            where span_name = 'poll feed'
            having count(*) = 0
        """,
        time_window="1h",
        frequency="15m",
        notify_when="has_matches",
    ),
    Alert(
        slug="stalled-jobs",
        name="stalled-jobs",
        description="A worker died holding jobs. Nothing else notices this.",
        query="""
            select message, service_name, trace_id
            from records
            where level >= 'warn' and message like '%stalled jobs%'
            order by start_timestamp desc
        """,
        time_window="15m",
        frequency="15m",
        notify_when="has_matches",
    ),
    Alert(
        slug="task-failures",
        name="task-failures",
        description="A queue job raised. Retries mean one of these is not an emergency.",
        query="""
            select
              attributes->>'job.task' as task,
              attributes->>'job.queue' as queue,
              otel_status_message as failure,
              trace_id
            from records
            where level >= 'error' and span_name like 'task %'
            order by start_timestamp desc
        """,
        time_window="1h",
        frequency="15m",
        notify_when="has_matches",
    ),
    Alert(
        slug="feed-suspended",
        name="feed-suspended",
        description="A feed failed enough times to be given up on. Silent data loss otherwise.",
        query="""
            select message, trace_id
            from records
            where level >= 'warn' and message like 'suspending feed%'
            order by start_timestamp desc
        """,
        time_window="24h",
        frequency="1h",
        notify_when="matches_changed",
    ),
)


@dataclass(frozen=True)
class Telemetry:
    write_token: pulumi.Output[str]


def provision(project_name: str, alert_webhook: pulumi.Output[str] | None = None) -> Telemetry:
    project = logfire.Project(
        "project",
        name=project_name,
        description="Feed archive — app, worker and queue traces",
        visibility="private",
    )

    # No expires_at: an expiring telemetry token fails silently.
    token = logfire.WriteToken("write-token", project_id=project.id)

    _alerts(project.id, alert_webhook)
    _dashboards(project.id)

    return Telemetry(write_token=token.token)


def _alerts(project_id: pulumi.Output[str], webhook: pulumi.Output[str] | None) -> None:
    """Nothing is created until there is somewhere to deliver to — an alert with no
    channel silently does nothing."""
    if webhook is None:
        webhook = pulumi.Config().get_secret("logfireAlertWebhook")
    if webhook is None:
        return

    channel = logfire.Channel(
        "alert-channel",
        name="old-news-alerts",
        active=True,
        config=logfire.ChannelConfigArgs(type="webhook", format="auto", url=webhook),
    )

    for alert in ALERTS:
        logfire.Alert(
            alert.slug,
            project_id=project_id,
            name=alert.name,
            description=alert.description,
            query=alert.query.strip(),
            time_window=alert.time_window,
            frequency=alert.frequency,
            notify_when=alert.notify_when,
            environments=ENVIRONMENTS,
            channel_ids=[channel.id],
            active=True,
        )


def _dashboards(project_id: pulumi.Output[str]) -> None:
    """Whatever has been exported into `logfire/dashboards/`, named by filename."""
    if not DASHBOARDS.is_dir():
        return

    for definition in sorted(DASHBOARDS.glob("*.json")):
        slug = definition.stem
        body = definition.read_text()
        logfire.Dashboard(
            f"dashboard-{slug}",
            project_id=project_id,
            # The exported file already names itself; a second name here would be a
            # second thing to keep in step.
            name=json.loads(body)["spec"]["display"]["name"],
            slug=slug,
            definition=body,
        )
