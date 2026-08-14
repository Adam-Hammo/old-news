# old-news

RSS feed reader. Building features that I want and using new packages/features that I want to use.

## Quickstart

```sh
brew install just uv
cp .env.example .env
just install
just up
```

That builds a Postgres image with `pgvector` and `pg_search`, applies migrations, and starts the API
and a worker.

Drop an OPML export from whatever reader you use now into `local/feeds.opml` and subscribe to the
lot. Nothing in `local/` is ever committed.

```sh
just opml-import                    # reads local/feeds.opml
just opml-export > local/feeds.opml # and back out again
```

The worker picks the feeds up within a minute.

|          |                                                           |
| -------- | --------------------------------------------------------- |
| API      | <http://localhost:8000>                                   |
| OpenAPI  | <http://localhost:8000/schema>                            |
| Admin    | <http://localhost:8000/admin> (`admin` / `admin` locally) |
| Postgres | `localhost:55432` — deliberately not 5432                 |

`just` on its own lists every recipe. The ones you'll use:

```sh
just check          # lint + typecheck + tests
just test           # everything, spins up a real Postgres
just test unit      # fast subset, no Docker
just lint           # every formatter and linter, every file type
just migration NAME # generate a migration from model changes
just opml-import    # subscribe to everything in local/feeds.opml
just admin-password # hash a password for the admin UI
just logs worker
just psql
just nuke           # down + drop the volume
```

## Layout

```text
src/old_news/
  config/            pydantic-settings, one module per section
  observability/     telemetry.py — installs the global OTel provider
  db/
    base.py          DeclarativeBase, naming conventions, uuidv7 keys
    session.py       async engine and session
    models/          feed, subscription, document, item (+ item_versions)
    migrations/      alembic
  fetch/             client.py — httpx2 lives only here
  ingest/            polling: service, store, parser, normalise, schedule
  subscriptions/     service, opml, discover
  passwords.py       scrypt hashing for the admin login
  api/
    app.py           Litestar factory and lifespan
    admin.py         sqladmin, mounted as an ASGI sub-application
    routes/          health.py; a read surface lands here
  tasks/
    app.py           the procrastinate App
    ingest.py        schedule_polls + poll_feed
    maintenance.py   registered tasks
tests/
  unit/              no Docker, no network beyond loopback
  integration/       needs a real Postgres
infra/
  resources/         one module per vendor
  ansible/roles/     app + backup
docker/
  postgres.Dockerfile   pg18 + pgvector + pg_search, multi-arch
  initdb/               CREATE EXTENSION on first boot
compose.yaml            the deploy contract — any Docker host runs this
compose.override.yaml   local dev only; auto-loaded, not used on the server
```

Each package owns its own dataclasses. There's no ports/adapters layer: swapping a library means
rewriting one module, and the dataclass it returns is what keeps callers honest.

Feature packages land as siblings of `fetch/` when they're built — `extract/`, `enrich/`,
`backfill/`, `library/`. See [CLAUDE.md](CLAUDE.md).

## Picking the admin password

Admin is full CRUD over the archive, so it never goes on a public interface. It still wants a
password, because the hash is what stops the plaintext existing in `.env`, in `pulumi stack output`,
in the Ansible variable file and in the box's environment at once.

`just admin-password` prompts for one and prints the line to use. Nothing is stored on your machine.

```sh
just admin-password                 # -> OLD_NEWS_ADMIN__PASSWORD_HASH=scrypt:32768:...
```

Locally, paste it into `.env`. Leave it unset and the development password `admin` applies, with a
warning on every boot.

For the box, the hash is stack config — the plaintext never leaves your machine:

```sh
cd infra
pulumi config set --secret adminPasswordHash "$(just admin-password | cut -d= -f2-)"
just deploy <sha>
```

Production refuses to start without it. That is deliberate: a reachable admin UI on a default
password is worse than a failed deploy.

## Configuration

Everything is environment variables, `OLD_NEWS_`-prefixed, nested with `__`:

```sh
OLD_NEWS_DATABASE__URL=postgres://old_news:old_news@localhost:55432/old_news
OLD_NEWS_API__PORT=8000
OLD_NEWS_TELEMETRY__ENABLED=true
OLD_NEWS_TELEMETRY__LOGFIRE_TOKEN=...
```

`.env.example` is the full list. No domain or host is baked in anywhere.

## Telemetry

Off by default, so the app runs with no accounts anywhere. Set `OLD_NEWS_TELEMETRY__ENABLED=true`
and a Logfire token and spans start flowing.

`telemetry.configure()` is the only module that imports `logfire`. It installs the global
OpenTelemetry provider; Litestar's `OpenTelemetryPlugin` and everything else emit into plain OTel.
Pointing at a different backend is a change to one function.

## Tests

```sh
just test        # everything, including a real Postgres
just test unit   # ~1s, no Docker
```

Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The deployed box

Reachability is Tailscale only — the app binds loopback and `tailscale serve` terminates TLS on the
MagicDNS name. There is no public address and no DNS record to buy.

|         |                                                |
| ------- | ---------------------------------------------- |
| OpenAPI | `https://<host>.<tailnet>.ts.net/schema`       |
| Health  | `https://<host>.<tailnet>.ts.net/health/ready` |
| Admin   | `https://<host>.<tailnet>.ts.net/admin`        |

Subscriptions go in over ssh rather than over HTTP — there is no write API yet, and the container is
read-only, so the OPML is piped in rather than copied:

```sh
just host=<host>.<tailnet>.ts.net opml-import
```

`host=` works on every operational recipe — `logs`, `ps`, `psql`, `backup`, `restore`, `opml-export`
— so the same command reads the local stack or the box. Lifecycle recipes (`up`, `down`, `nuke`) are
local-only on purpose: the box is deployed, never built in place.

## Deploying

```sh
docker compose -f compose.yaml up -d --build
```

Note the explicit `-f`: it excludes `compose.override.yaml`, which exposes the database port and
mounts source for reload. Neither belongs on the server.

Set `PG_SHARED_BUFFERS=3GB`, `PG_EFFECTIVE_CACHE_SIZE=9GB` and `PG_MAINTENANCE_WORK_MEM=512MB` on a
12 GB box. That's good tuning anyway, and it keeps memory utilisation above the 20% floor Oracle
uses to decide an Always Free instance is idle enough to reclaim.

## Why the Postgres image is custom

`paradedb/paradedb:0.25.2-pg18` exists and is published for both amd64 and arm64, so building our
own isn't about architecture support. It's about what their entrypoint does: it creates PostGIS,
`postgis_topology`, `pg_ivm`, `pg_cron` and `pg_stat_statements` in `template1` _and_ in your
database, sets a `paradedb` search_path, and auto-tunes memory over whatever you configured.

Every `pg_dump` would then need PostGIS present to restore — not a dependency an archive meant to
outlive its own hardware should carry. Building on `postgres:18.4-trixie` keeps the extension list
to `vector` and `pg_search`, and gets pgvector 0.8.6 rather than the 0.8.4 they bundle.

Postgres 18 also moved its volume mount: it's `/var/lib/postgresql`, not `/var/lib/postgresql/data`,
so PGDATA lands in a version-named subdirectory and `pg_upgrade --link` stays possible across
majors.
