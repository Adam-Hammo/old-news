"""One stack, one source of truth.

Every secret is generated here or held as encrypted stack config. Ansible reads them
from `pulumi stack output` and stores none of them.
"""

import pulumi
from resources import (
    limits_oci,
    monitoring_healthchecks,
    passwords,
    storage_b2,
    tailnet,
    telemetry_logfire,
)
from resources.compute_oci import provision as provision_host

config = pulumi.Config()

host = provision_host()
generated = passwords.generate()
repository = storage_b2.provision(config.require("b2Bucket"))
checks = monitoring_healthchecks.provision()
telemetry = telemetry_logfire.provision(
    config.get("logfireProject") or "old-news",
    alert_webhook=checks.alert_webhook if checks else None,
)
access = tailnet.provision()
limits_oci.provision()

pulumi.export("host_name", host.name)
pulumi.export("host_username", host.username)
pulumi.export("host_private_ip", host.private_ip)
pulumi.export("host_public_ip", host.public_ip)

# Named as the Ansible variables that consume them: the deploy pipes these straight
# into --extra-vars, so renaming an output renames the variable.
pulumi.export("postgres_password", generated.postgres_password)
pulumi.export("restic_password", generated.restic_password)
pulumi.export("b2_bucket", repository.bucket)
pulumi.export("b2_region", config.require("b2Region"))
pulumi.export("b2_key_id", repository.key_id)
pulumi.export("b2_application_key", repository.application_key)
pulumi.export("logfire_token", telemetry.write_token)
pulumi.export("tailscale_auth_key", access.server_auth_key)

# Chosen rather than generated — it is typed into a login form — so it is stack
# config, not passwords.generate(). Only the scrypt hash ever leaves your machine.
pulumi.export("admin_password_hash", config.require_secret("adminPasswordHash"))

# A capability URL: anyone holding it can forge a healthy signal. Minted by the
# checks module when it runs; the config key is the fallback, and the check it names
# can be deleted by hand once a deploy has repointed the timer.
pulumi.export(
    "heartbeat_url",
    checks.heartbeat_url if checks else config.require_secret("heartbeatUrl"),
)
