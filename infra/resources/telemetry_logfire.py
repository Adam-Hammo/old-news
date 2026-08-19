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


# The provider rejects anything else, and only says so once a preview has reached
# Logfire — a CI round trip to learn that 26h is not a window. Checked on import
# instead. Note the two sets differ: frequency has no 7d or 30d.
TIME_WINDOWS = frozenset(
    {"1m", "2m", "5m", "10m", "15m", "30m", "1h", "6h", "12h", "24h", "7d", "30d"}
)
FREQUENCIES = frozenset({"1m", "2m", "5m", "10m", "15m", "30m", "1h", "6h", "12h", "24h"})


@dataclass(frozen=True)
class Alert:
    slug: str
    name: str
    description: str
    query: str
    time_window: str
    frequency: str
    notify_when: str

    def __post_init__(self) -> None:
        for field, value, allowed in (
            ("time_window", self.time_window, TIME_WINDOWS),
            ("frequency", self.frequency, FREQUENCIES),
        ):
            if value not in allowed:
                raise ValueError(f"{self.slug}: {field} {value!r} must be one of {sorted(allowed)}")


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
        slug="collector-silent",
        name="collector-silent",
        description="No host metrics. The collector is the only thing that sends these, "
        "it has no dependents, and it restarts forever — so it dies quietly.",
        # Same inversion as ingest-silent: silence has to become a row to match on.
        query="""
            select count(*) as points
            from metrics
            where metric_name = 'system.memory.usage'
            having count(*) = 0
        """,
        time_window="1h",
        frequency="15m",
        notify_when="has_matches",
    ),
    Alert(
        slug="backup-stale",
        name="backup-stale",
        description="No backup in a day. Daily timer, an hour of jitter, and a night of grace.",
        # 26h is not an allowed window, and 24h would cry wolf: `OnCalendar=daily`
        # with an hour of RandomizedDelaySec puts up to 25h between two good runs.
        # So look over a week and measure the staleness rather than the emptiness.
        # COALESCE is what turns "reported nothing all week" into a row to match on.
        query="""
            select max(recorded_timestamp) as last_backup
            from metrics
            where metric_name = 'backup.snapshot.age'
            having coalesce(max(recorded_timestamp), now() - interval '999 days')
                   < now() - interval '26 hours'
        """,
        time_window="7d",
        frequency="1h",
        notify_when="has_matches",
    ),
    Alert(
        slug="unit-failed",
        name="unit-failed",
        description="A systemd unit on the box failed — backup, its verification, or keepbusy.",
        query="""
            select
              start_timestamp,
              attributes->>'systemd.unit' as unit,
              attributes->>'systemd.result' as result,
              message
            from records
            where service_name = 'old-news-host' and level >= 'error'
            order by start_timestamp desc
        """,
        time_window="24h",
        frequency="15m",
        notify_when="matches_changed",
    ),
    Alert(
        slug="disk-filling",
        name="disk-filling",
        description="The root filesystem is over 80%. The archive only grows, so this one is terminal.",
        query="""
            select round(max(metric_avg(value))::numeric * 100, 1) as used_percent
            from metrics
            where metric_name = 'system.filesystem.utilization'
              and attributes->>'mountpoint' = '/'
            having max(metric_avg(value)) > 0.8
        """,
        time_window="1h",
        frequency="1h",
        notify_when="has_matches",
    ),
    Alert(
        slug="feed-given-up",
        name="feed-given-up",
        description="A feed failed enough times to stop being polled. Silent data loss otherwise.",
        query="""
            select message, trace_id
            from records
            where level >= 'warn' and message like 'giving up on feed%'
            order by start_timestamp desc
        """,
        time_window="24h",
        frequency="1h",
        notify_when="matches_changed",
    ),
    Alert(
        slug="captures-failing",
        name="captures-failing",
        description="Article capture is running and never succeeding. Nothing else notices: "
        "a 403 is a successful job, so the queue stays clean and every feed reads healthy.",
        # Not "no captures at all" — a drained corpus is legitimately quiet, and quiet
        # means no spans either. The failure worth catching is work being done and none
        # of it landing, which is what ran for 24 hours behind a saturated batch.
        #
        # `like '2%'` rather than a cast: a span that decided not to fetch — robots,
        # a closed host — carries no status at all, and a cast on null errors.
        query="""
            select
              count(*) as attempts,
              sum(case when attributes->>'http.response.status_code' like '2%' then 1 else 0 end)
                as stored
            from records
            where span_name = 'capture page'
            having count(*) > 0
               and sum(case when attributes->>'http.response.status_code' like '2%' then 1 else 0 end)
                   = 0
        """,
        time_window="1h",
        frequency="15m",
        notify_when="has_matches",
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
