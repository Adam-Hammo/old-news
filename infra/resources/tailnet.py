"""The tailnet policy, which is the whole access story once port 22 is closed.

`pulumi up` replaces the policy wholesale, so this has to carry every rule the tailnet
needs — including the ones that were already there.
"""

import json
from dataclasses import dataclass

import pulumi
import pulumi_tailscale as tailscale

SERVER_TAG = "tag:server"
CI_TAG = "tag:ci"

POLICY = {
    "tagOwners": {
        # Who may *assign* a tag. Nothing to do with traffic.
        SERVER_TAG: ["autogroup:admin"],
        CI_TAG: ["autogroup:admin"],
    },
    # Carried over as-is. Narrowing it means enumerating everything else in use.
    "grants": [
        {"src": ["*"], "dst": ["*"], "ip": ["*"]},
    ],
    "ssh": [
        {
            # Carried over. Covers your own devices, but not the box: a tagged device
            # is owned by the tag, so `self` stops matching it. Hence the rule below.
            "action": "check",
            "src": ["autogroup:member"],
            "dst": ["autogroup:self"],
            "users": ["autogroup:nonroot", "root"],
        },
        {
            "action": "check",
            "src": ["autogroup:member"],
            "dst": [SERVER_TAG],
            "users": ["ubuntu"],
        },
        {
            # `accept`, not `check`: check needs a browser no runner has.
            "action": "accept",
            "src": [CI_TAG],
            "dst": [SERVER_TAG],
            "users": ["ubuntu"],
        },
    ],
}


@dataclass(frozen=True)
class Tailnet:
    server_auth_key: pulumi.Output[str]


def provision() -> Tailnet:
    # Only what Serve needs: the provider patches the fields it is given, and several
    # of the others are rejected outright on a free plan even when set to the value
    # they already hold.
    tailscale.TailnetSettings("settings", https_enabled=True)

    tailscale.Acl(
        "acl",
        acl=json.dumps(POLICY, indent=2),
        overwrite_existing_content=True,
        # Resetting would drop tagOwners, invalidating the box's tag.
        reset_acl_on_destroy=False,
    )

    # Enrols a rebuilt box. 90 days is Tailscale's maximum; `recreate_if_invalid`
    # regenerates it so the stack output is never a dead key.
    key = tailscale.TailnetKey(
        "server-auth-key",
        description="old-news server enrolment",
        ephemeral=False,
        preauthorized=True,
        reusable=True,
        tags=[SERVER_TAG],
        expiry=7776000,
        recreate_if_invalid="always",
    )

    return Tailnet(server_auth_key=key.key)
