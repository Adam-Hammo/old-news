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

|               |                                                             |
| ------------- | ----------------------------------------------------------- |
| API           | <http://localhost:8000>                                     |
| OpenAPI       | <http://localhost:8000/schema>                              |
| Piccolo Admin | <http://localhost:8000/admin> (run `just admin-user` first) |
| Postgres      | `localhost:55432` — deliberately not 5432                   |

`just` on its own lists every recipe. The ones you'll use:

```sh
just check          # lint + typecheck + tests
just test           # everything, spins up a real Postgres
just test unit      # fast subset, no Docker
just lint           # every formatter and linter, every file type
just migration NAME # generate a migration from model changes
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
    piccolo_conf.py  the engine
    piccolo_app.py   migration registry
    tables/          base.py (uuidv7 keys), procrastinate.py (queue mirrors)
    migrations/
  fetch/             client.py — httpx2 lives only here
  api/
    app.py           Litestar factory and lifespan
    admin.py         Piccolo Admin, mounted over the procrastinate tables
    routes/          health.py; greader/ and native/ land here
  tasks/
    app.py           the procrastinate App
    maintenance.py   registered tasks
tests/
  unit/              no Docker, no network beyond loopback
  integration/       needs a real Postgres
infra/
  provider_oci.py    the only cloud-specific file
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
`backfill/`, `blob/`. See [CLAUDE.md](CLAUDE.md).

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
