"""Logfire, minted rather than copied out of the UI so rotation is a `pulumi up`.

The provider is young (0.1.15). If it churns, delete these two resources and hold the
token as secret config instead; nothing else in the stack changes.
"""

from dataclasses import dataclass

import pulumi
import pulumi_logfire as logfire


@dataclass(frozen=True)
class Telemetry:
    write_token: pulumi.Output[str]


def provision(project_name: str) -> Telemetry:
    project = logfire.Project(
        "project",
        name=project_name,
        description="Feed archive — app, worker and queue traces",
        visibility="private",
    )

    # No expires_at: an expiring telemetry token fails silently.
    token = logfire.WriteToken("write-token", project_id=project.id)

    return Telemetry(write_token=token.token)
