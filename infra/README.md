# infra

Pulumi provisions the box, Ansible configures it. Nothing here is exercised by CI — it touches a
real cloud account.

## Layout

```text
__main__.py         entrypoint; provider-neutral
provider.py         the Host dataclass every provider returns
provider_oci.py     the only OCI-specific file
cloud-init.yaml     tailscale + docker on first boot
ansible/
  playbook.yml
  roles/app/        checkout, .env, systemd unit wrapping docker compose
  roles/backup/     restic -> B2 on a daily timer
```

Swapping cloud provider means writing `provider_hetzner.py` that returns a `Host`, and changing one
import in `__main__.py`. Ansible doesn't know or care which cloud it's on.

## First run

```sh
cp Pulumi.prod.yaml.example Pulumi.prod.yaml
pulumi stack init prod
pulumi config set --secret tailscaleAuthKey tskey-auth-...
just tf-up
```

Then, once the host has joined your tailnet:

```sh
cp ansible/inventory.example.ini ansible/inventory.ini   # edit the hostname
just provision
```

## Expect `Out of host capacity`

This is normal, not a misconfiguration. A1 capacity in Sydney and Melbourne is chronically
exhausted. Loop:

```sh
until just tf-up; do sleep 120; done
```

The create timeout is already set to 30m so a single attempt doesn't fail fast.

## Before you trust any of this

**Perform one real restore.** An untested backup is a hypothesis, and the archive is the only part
of this system that can't be rebuilt.

```sh
restic snapshots
restic dump latest old-news.sql.gz | gunzip | pg_restore -d old_news
```

## Prerequisites

- An OCI account **upgraded to Pay As You Go**. Oracle reclaims Always Free compute when CPU,
  network and memory all sit under 20% over a 7-day window — which a feed poller does comfortably.
  Upgrading exempts you, and is the single most likely way to lose the box if you skip it.
- A `$1` budget alert set in the OCI console before you provision anything.
- A Tailscale auth key, and a B2 bucket with an application key scoped to it.
