"""healthchecks.io checks, so the URLs things ping are minted rather than pasted.

Skipped entirely when `healthchecksio:apiKey` is unset, because a stack that cannot
reach the provider should still come up.
"""

from dataclasses import dataclass

import pulumi
import pulumi_healthchecksio as healthchecksio

# Logfire evaluates on its own schedule and only ever reports failure, so this check
# must not expire on its own — `/fail` is the only thing that should turn it red.
NEVER = 365 * 24 * 3600

# The timer pings every 5 minutes. The grace covers a slow boot or one missed run;
# below that a reboot pages you.
HEARTBEAT_PERIOD = 300
HEARTBEAT_GRACE = 900


@dataclass(frozen=True)
class Checks:
    heartbeat_url: pulumi.Output[str]
    alert_webhook: pulumi.Output[str]


def provision() -> Checks | None:
    if pulumi.Config("healthchecksio").get_secret("apiKey") is None:
        return None

    # "The box is alive", pinged by old-news-heartbeat.timer once it sees /health/ready.
    heartbeat = healthchecksio.Check(
        "heartbeat",
        name="old-news",
        desc="Readiness heartbeat from the box. Ping means /health/ready answered.",
        tags=["old-news"],
        timeout=HEARTBEAT_PERIOD,
        grace=HEARTBEAT_GRACE,
    )

    # Deliberately separate: an application alert must not claim the box is down.
    alerts = healthchecksio.Check(
        "logfire-alerts",
        name="old-news-alerts",
        desc="Logfire alerts land here.",
        tags=["old-news", "logfire"],
        timeout=NEVER,
        grace=300,
    )

    return Checks(
        heartbeat_url=heartbeat.ping_url,
        alert_webhook=alerts.ping_url.apply(lambda url: f"{url}/fail"),
    )
