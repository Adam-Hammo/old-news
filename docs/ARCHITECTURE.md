# Architecture

How the code is laid out, and the reasoning behind it.

## The shape

```text
src/old_news/
  config/            settings, one module per section
  observability/     telemetry — installs the global OTel provider
  db/                engine, tables, migrations
  fetch/             HTTP client
  api/               Litestar app, routes, admin mount
  tasks/             procrastinate app and registered tasks
```

Everything is a package, each owning its own frozen dataclasses.

### There is no ports/adapters layer, deliberately

A `Protocol` doesn't make a library swappable. What does is that its call sites are few and that
**the types crossing the boundary are ours, not the library's**. `fetch.Response` is the contract;
`httpx2` is an implementation detail that never escapes `fetch/`.

So the rule is a rule about imports, not about interfaces: a third-party library gets imported by
exactly one package. Replacing `trafilatura` should be a diff confined to `extract/`.

Persistence is exempt. Piccolo and Postgres are load-bearing — `pg_search`, `pgvector`,
`procrastinate` and partitioning all assume them, and a repository layer would buy a migration you
will never perform. Query with Piccolo directly.

## Where services live

Each feature package owns its own logic in `service.py`, growing to a `services/` subpackage if it
needs to. Routes and tasks are adapters: they parse input, call a service, and shape the response.
Neither should contain business rules.

```text
src/old_news/ingest/
  service.py       poll_feed() — orchestration lives here
  parser.py        feedparser boundary
```

The call chain for a scheduled poll:

```text
tasks/ingest.py  ──►  ingest/service.py  ──►  fetch/    (HTTP)
                             │                 db/      (persistence)
                             └────────────────► extract/ (article text)
```

And for a request:

```text
api/routes/greader.py  ──►  ingest/service.py  ──►  db/
```

A service never imports from `api/` or `tasks/`. That's the only direction rule, and it's what keeps
the same logic reachable from both a worker and an HTTP handler.

Feature packages still to be built: `ingest/`, `extract/`, `enrich/`, `backfill/`, `blob/`.

## Configuration

Environment variables only, `OLD_NEWS_`-prefixed, nested with `__`. No host, domain or path is baked
in anywhere — that is the specific trap that makes self-hosted feed readers unmovable.

`config/` is pure data. It reads no files at import beyond `.env` and reaches nothing over a
network.

## Database

`db/piccolo_conf.py` owns the engine. Piccolo finds it through `PICCOLO_CONF`, which the justfile,
the Dockerfile and the test suite all set to `old_news.db.piccolo_conf`; without it Piccolo looks
for a top-level `piccolo_conf` and fails.

There are no application tables yet — the domain model is deliberately absent.

Procrastinate owns its own tables and migrates them itself; `db/migrate.py` applies its schema only
when absent, because `procrastinate schema --apply` fails on a second run and would break every
restart. Successful jobs are deleted on completion and a daily task sweeps the rest, so the queue
tables stay small — Postgres holds the queue, and the history lives in traces.

Tables get one module each under `db/tables/`. Migrations are generated, not written:

```sh
just migration "what changed"
just migrate
```

### Schema patterns

Piccolo models ordinary columns well. The Postgres-specific half — partitions, extension types,
extension indexes — is written by hand in migrations. That is the normal way of working here, not a
workaround.

**Server-side defaults.** Piccolo expresses these as `Default` subclasses, not plain callables. This
distinction is a trap: a bare callable is evaluated _once_ and frozen into the generated DDL as a
literal, so every row inserted outside Piccolo would collide on the same value.

```python
id = UUID(primary_key=True, default=UUID7())   # DEFAULT uuidv7()  — correct
id = UUID(primary_key=True, default=uuid7)     # DEFAULT '019ff…'  — frozen literal
```

`UUID7` needs Postgres 18. The same applies to `TimestamptzNow()` over `datetime.now`. For a default
Piccolo doesn't ship, subclass `Default`: `postgres` returns the SQL fragment, `python()` the value
used for Piccolo's own inserts.

**Custom column types.** `column_type` is overridable, which covers extension types in a dozen
lines:

```python
class Vector(Column):
    def __init__(self, dimensions: int, **kwargs):
        self.dimensions = dimensions
        super().__init__(**kwargs)

    @property
    def column_type(self) -> str:
        return f"VECTOR({self.dimensions})"
```

**Everything else** — monthly partitions, the BM25 index, DiskANN — is raw DDL in a migration.
`db.run_sql()` is the escape hatch at runtime.

`piccolo_conf.py` also registers Piccolo's `user` and `session_auth` apps — they back Admin's login,
and without them `just admin-user` has no table to write to. `just migrate` runs `forwards all` for
that reason.

## Telemetry

`observability/telemetry.py` is the only module that imports `logfire`. It installs the global
OpenTelemetry provider; everything else — including Litestar's `OpenTelemetryPlugin` — emits into
plain OTel and knows nothing about the backend.

It's off unless `OLD_NEWS_TELEMETRY__ENABLED` is set, so the app runs with no accounts anywhere.

### What is instrumented

|               |                                                                         |
| ------------- | ----------------------------------------------------------------------- |
| HTTP server   | Litestar's OTel plugin                                                  |
| Postgres      | `instrument_asyncpg` (Piccolo) and `instrument_psycopg` (procrastinate) |
| Outbound HTTP | a span per fetch, in `fetch/client.py`                                  |
| Jobs          | a span per job, via procrastinate worker middleware                     |
| Queue depth   | gauges from a periodic task, once a minute                              |
| Logs          | stdlib logging bridged to Logfire, so a log line carries its trace id   |

Jobs are linked to whatever deferred them: `tasks/tracing.defer()` injects the W3C traceparent as a
reserved `__traceparent` kwarg, and the worker middleware uses it as the span's parent.
`tasks.tracing.task()` strips it before the task function is called, so task signatures never see
it. Deferring with plain `defer_async` still works — the job just starts a new trace.

### Volume is managed by filtering, not sampling

Logfire's free tier is 10M spans/month, and an unfiltered feed poller gets close to it before doing
anything useful. Two things are filtered out at the source:

- **Database spans are off** unless `OLD_NEWS_TELEMETRY__INSTRUMENT_DATABASE=true`. One span per
  query roughly triples the volume; turn it on for an afternoon when a query is the problem.
- **Housekeeping tasks are untraced.** `queue_metrics` runs every minute forever and a successful
  run tells you nothing. Failures still increment a counter and still log.

Sampling was considered and rejected. Head sampling propagates correctly through the traceparent,
but discards failures — the only polls worth keeping. Tail sampling keeps failures, but buffers
every span of a trace in memory and decides per process, so with a separate app and worker it would
emit half of each cross-process trace.

### Never put a secret where telemetry can reach it

Three places leak, and only the first is obvious:

- **Query strings.** The `http.url` span attribute keeps them, and Logfire lists `http.url` in its
  `SAFE_KEYS`, so scrubbing never touches it. Routes taking a secret in the query string go in
  `UNTRACED_PATHS` — that is the only thing that works. `fetch/` records a redacted URL for the same
  reason.
- **Task kwargs.** Procrastinate logs them at INFO, and those logs now reach Logfire. So tasks take
  identifiers, not values: `poll_feed(feed_id)`, never `poll_feed(url)` — feed URLs carry API keys.
  The job span deliberately omits kwargs entirely.
- **Span attributes generally.** They are not scrubbed once emitted. Attributes are named
  explicitly, never splatted from a dict of unknown provenance.

`tests/unit/test_telemetry.py` and the fetch tests assert all of this, and they fail if the
protection is removed.

## Tests

Split by what they need, not by what they're called:

- `tests/unit/` — nothing external. No Docker, no network beyond loopback.
- `tests/integration/` — a real Postgres, built from `docker/postgres.Dockerfile` and run by
  testcontainers, so `pg_search` and `pgvector` are genuinely present.

Mirror the `src/` path. Don't mock Postgres and don't stub HTTP transports; `fetch/` is tested
against a real server on a loopback socket, which is how the redirect and 304 paths get exercised at
all.

**The app always owns its connection pool.** asyncpg binds a pool to the loop that created it, and
`AsyncTestClient` runs handlers on a loop of its own — so a pool opened by a fixture is unusable
from inside a request. The `migrated` fixture therefore closes its pool after running migrations,
and API tests get theirs from the app's own lifespan, which is exactly what happens in production. A
fixture that leaves a pool open will make readiness checks pass for the wrong reason.

## Deployment

`compose.yaml` is the contract: any host that runs Docker runs this. `compose.override.yaml` is
local-only and auto-loaded, which is why the server runs `docker compose -f compose.yaml`
explicitly.

`infra/` provisions and configures the host, and is not exercised by CI — it touches a real cloud
account. Provider-specific code is confined to `infra/provider_oci.py`, which returns a `Host`.
Adding a cloud is one new module and one changed import.

## Security

- Piccolo Admin is never publicly reachable. It has session auth, but it is still full CRUD over the
  entire archive.
- Postgres is never published in `compose.yaml`. The dev port binding lives in the override file.
- No registration endpoint, ever. Single user, seeded credentials.
- Never log request bodies for `/accounts/ClientLogin` — it carries the API password.
