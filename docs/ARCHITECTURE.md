# Architecture

How the code is laid out, and the reasoning behind it.

## The shape

```text
src/old_news/
  # foundations
  config/            settings, one module per section
  observability/     telemetry — installs the global OTel provider
  db/                engine, models, alembic migrations
  tasks/             procrastinate app and registered tasks

  # talking to publishers
  fetch/             HTTP client
  politeness/        host grouping and request spacing
  robots/            robots.txt: fetch, store, honour

  # what we keep
  ingest/            polling: fetch, parse, normalise, store
  extract/           the page behind the teaser, and what we read out of it
  subscriptions/     what we follow: add, OPML, discovery

  # what the reader wants
  training/          rules about what is worth keeping

  # edges
  api/               Litestar app, routes, admin mount
```

Everything is a package, each owning its own frozen dataclasses. The groups above are comments, not
directories — the layering is real but flat on disk, because a package that has to be reached
through a parent is harder to move than one that doesn't.

`tests/unit/test_architecture.py` asserts this list against the filesystem, so growing a new
top-level package fails in the diff that grows it. That is the point: sprawl is cheapest to argue
about at the moment it appears.

### There is no ports/adapters layer, deliberately

A `Protocol` doesn't make a library swappable. What does is that its call sites are few and that
**the types crossing the boundary are ours, not the library's**. `fetch.Response` is the contract;
`httpx2` is an implementation detail that never escapes `fetch/`.

So the rule is a rule about imports, not about interfaces: a third-party library gets imported by
exactly one package. Replacing `trafilatura` should be a diff confined to `extract/`.

Persistence is exempt. SQLAlchemy and Postgres are load-bearing — `pg_search`, `pgvector`,
`procrastinate` and partitioning all assume them, and a repository layer would buy a migration you
will never perform. Query with SQLAlchemy directly.

The one thing that behaves like a repository is `ingest/store.py`, and only because "ingestion
appends, never overwrites" has to live in exactly one place or the third caller violates it.

### The reading model is on the models

Anything a reader asks that is _structural_ is a relationship, not a query written again at each
call site: `Item.current_version`, `Item.current_extraction`, `ItemVersion.latest_capture`,
`ItemVersion.latest_extraction`. Each is `viewonly` with a `primaryjoin` doing the anti-join, and
each is `lazy="raise"` so a forgotten `joinedload` fails loudly instead of firing a query per row.

Two of them are deliberately not scoped to the head version. `Item.current_extraction` and
`Item.reading_body` span the whole chain, because an edit makes a new version the head and its page
waits out the settle window before being fetched — head-scoped, they would blank an article for an
hour every time a publisher touched it. `ItemVersion.reading_body` answers the narrower question
about one version, which is what a history view wants.

`reading_body` is a `hybrid_property`, so a river can select and sort on it without loading every
body into Python. That puts one policy — which of two texts is fuller — in the model layer rather
than a service, which is the exception to the rule below and is why it is written down here.

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
                             └────────────────► db/      (documents, compressed)
```

Extraction is not on that chain, deliberately. It is three sweeps of its own on their own queue,
each finding work by what the archive is missing rather than by what a poll just wrote:

```text
tasks/extract.py ──► extract/due.py      what has no page      ──► extract/capture.py
                 ──► extract/service.py  what has no text      ──► extract/article.py
                 ──► extract/images.py   what has no picture
```

A failing extractor cannot fail a poll, retries are independent, and re-capturing a five-year-old
article runs down exactly the same path as capturing one that arrived a minute ago.

And for a request:

```text
api/routes/greader.py  ──►  ingest/service.py  ──►  db/
```

A service never imports from `api/` or `tasks/`. That's the only direction rule, and it's what keeps
the same logic reachable from both a worker and an HTTP handler.

Feature packages still to be built: `enrich/`, `backfill/`, `blob/`.

## Configuration

Environment variables only, `OLD_NEWS_`-prefixed, nested with `__`. No host, domain or path is baked
in anywhere — that is the specific trap that makes self-hosted feed readers unmovable.

`config/` is pure data. It reads no files at import beyond `.env` and reaches nothing over a
network.

## Database

`db/session.py` owns the engine. `create_async_engine` opens nothing — connections are made lazily
on whichever loop first asks — so unlike a pre-opened pool it is safe to build outside a running
loop, which is what lets the admin mount hold it at construction time.

Alembic's `env.py` reads the URL from settings, so no host or credential is in `alembic.ini`. It
also filters `procrastinate_*` out of autogenerate: procrastinate owns that schema and migrates it
itself, and without the filter every revision opens with a dozen `drop_table` calls. `db/migrate.py`
applies Alembic and then procrastinate's schema, the latter only when absent, because
`procrastinate schema --apply` fails on a second run and would break every restart.

Models get one module each under `db/models/`. Migrations are generated, not written:

```sh
just migration "what changed"
just migrate
```

### Schema patterns

SQLAlchemy models ordinary columns well. The Postgres-specific half is `server_default=text(...)`,
`__table_args__` and, where there is no abstraction at all, `op.execute` inside a generated
revision. That is the normal way of working here, not a workaround.

**Server-side defaults.** `server_default=text("uuidv7()")` emits `DEFAULT uuidv7()`, so a row
inserted by anything other than this ORM still gets a key. A Python-side `default=` would not.
`uuidv7()` needs Postgres 18.

**Naming conventions are pinned** in `db/base.py`. Without them Alembic names constraints after
whatever Postgres invented and autogenerated revisions churn. Note the `ck` template interpolates
the name you supply, so a check constraint is named with the bare suffix.

**Foreign keys are not indexed automatically.** Postgres indexes the referenced side, never the
referencing one.

**`robots_policies.host` is a natural key with no foreign key**, and nothing points at the table. A
host is derived from a feed's URL whenever it is needed, so there is no stored copy to drift, and a
durable table referencing a disposable cache could not be dropped and rebuilt — which is the one
thing that table is for.

**Enums live in Python, strings live in Postgres.** A closed set of values is a `StrEnum` and a
`VARCHAR` with a check constraint built from its members by `db.base.one_of`, so the constraint
cannot drift from the enum. `sa.Enum` is not used for either half: a native Postgres type cannot
gain a value in the same transaction as the migration that needs it, and with `native_enum=False`
alembic renders the member _names_ into the constraint where the application writes the _values_,
which fails every insert. Columns are annotated `Mapped[str]`, because a string is what comes back —
and a `StrEnum` member compares equal to its own value, so `==` still reads naturally.

**Indexes follow the queries, not the columns.** A unique constraint's leading column already serves
lookups on it, so there is no separate index for `extractions.item_version_id`,
`extraction_images.extraction_id`, `image_captures.url_digest` or `zstd_dictionaries.dict_id`. What
a constraint cannot serve gets its own: `(extractor, extractor_version)` answers "which versions has
this extractor not done", and a partial index on `extraction_images.role` limited to slots with
nothing fetched stays small as the archive fills.

**Everything else** — monthly partitions, the BM25 index, DiskANN — is raw DDL in a revision.

### Stored bodies are compressed, sometimes against a dictionary

`db/bytes.py` is the only module that imports zstd. Everything stored as bytes — feed documents,
article pages — goes through it at one level, which is config rather than a constant.

Ten consecutive documents from one feed are near-identical, so a dictionary trained on them roughly
halves what each costs: 88 KB at the old default, 81 KB at level 12, 44 KB with a per-feed
dictionary. Article pages from one host gain less, because two pages share a template where two
documents share almost everything, so the two scopes are separate and `zstd_dictionaries` carries
exactly one of `feed_id` or `host_id`.

Three things make this safe to have done:

- **A frame names its own dictionary.** `get_frame_info(body).dictionary_id` is 0 or an id, so
  reading never depends on remembering what wrote it, and reading with the wrong one raises rather
  than returning plausible rubbish.
- **Nothing is ever rewritten.** A dictionary is immutable and outlives being current, because every
  body compressed against it stays that way. `documents.dictionary_id` and
  `page_captures.dictionary_id` are foreign keys, so Postgres refuses to drop one still in use and
  it cannot go missing from a dump that holds the bodies.
- **No dictionary is always correct.** A scope with too little to learn from — zstd's trainer
  refuses below a handful of samples — stays on plain zstd. That is the cold start and the fallback.

A retrain inserts rather than replaces. `dict_id` hashes the content, so an unchanged feed retrains
to the same dictionary; that is a no-op that moves `trained_at`, not a failed nightly job, which is
why the unique key is the dictionary and its scope together.

## Politeness is job options, not a scheduler

Nothing limits request rate inside `fetch/`. Doing it there would need a registry of hosts,
last-request timestamps, semaphores and an eviction policy for a dict that grows forever — at which
point `fetch/` has quietly become a scheduler.

Instead it is two options on a deferred job. `lock=f"host:{host}"` makes Postgres hand out one job
per host at a time, so a publisher with four feeds gets four visits in a row rather than four
simultaneous connections. `schedule_in` staggers a batch so those visits are spaced rather than
back-to-back. A failed job does not hold its lock, so one broken feed cannot stall the rest of its
host.

`robots.txt` reuses the same mechanism. Rules are refreshed by a periodic task into
`robots_policies`, one row per host, overwritten in place — a cache, so the append-only rules do not
apply. `Crawl-delay` comes back out as a longer `schedule_in`, and may only lengthen a wait, never
shorten one. A host that cannot be reached is carried on past: a publisher that failed to state its
rules has not prohibited anything, and refusing to fetch on a timeout would stop the archive every
time a CDN hiccups.

`politeness/` sits above `ingest/` because polling, robots refreshes and article fetches all need
the same host grouping.

### A queueing lock collision is not an error

`queueing_lock` means "only one of these may be waiting", but procrastinate reports the collision by
raising `AlreadyEnqueued` from `defer`. Unhandled in a sweep, that ends the sweep and silently
leaves every remaining item undeferred — feeds stop being polled and nothing says so except `failed`
climbing in the queue gauges. `tasks.tracing.defer_unless_queued()` is what both sweeps use instead,
and the skips are counted rather than thrown.

This matters more now than it used to: jobs wait on a per-host lock, so one still sitting in the
queue a minute later is ordinary rather than a sign of trouble.

## Telemetry

`observability/telemetry.py` is the only module that imports `logfire`. It installs the global
OpenTelemetry provider; everything else — including Litestar's `OpenTelemetryPlugin` — emits into
plain OTel and knows nothing about the backend.

It's off unless `OLD_NEWS_TELEMETRY__ENABLED` is set, so the app runs with no accounts anywhere.

### What is instrumented

|               |                                                                                     |
| ------------- | ----------------------------------------------------------------------------------- |
| HTTP server   | Litestar's OTel plugin                                                              |
| Postgres      | `instrument_asyncpg` (SQLAlchemy's driver) and `instrument_psycopg` (procrastinate) |
| Outbound HTTP | a span per fetch, in `fetch/client.py`                                              |
| Jobs          | a span per job, via procrastinate worker middleware                                 |
| Queue depth   | gauges from a periodic task, once a minute                                          |
| Logs          | stdlib logging bridged to Logfire, so a log line carries its trace id               |

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

**The app always owns its engine.** SQLAlchemy creates connections lazily, so an engine built
outside a loop is fine — but a _connection_ is still bound to the loop that opened it. Tests that
talk to Postgres directly get their own engine from the `database` fixture and dispose it; API tests
get theirs from the app's own lifespan, exactly as in production.

**Alembic runs its own event loop.** `env.py` calls `asyncio.run`, so anything that applies
migrations has to stay synchronous — which is why the `migrated` fixture is a plain function and
procrastinate's schema is applied by a separate async fixture.

## Dead code fails the build

`vulture` runs in pre-commit, configured in `pyproject.toml`. It cannot see code a framework reaches
for by name — sqladmin's declarative attributes, procrastinate's task registry, pytest's fixture
injection, columns read only through SQL — so those are named in `ignore_names` rather than hidden
behind a confidence threshold that would also swallow real findings. Prefer `_name` for a parameter
a framework's signature forces on you; vulture skips those, and it keeps generic names like `conn`
out of the ignore list.

## Deployment

`compose.yaml` is the contract: any host that runs Docker runs this. `compose.override.yaml` is
local-only and auto-loaded, which is why the server runs `docker compose -f compose.yaml`
explicitly.

Provider-specific code is confined to `infra/resources/compute_oci.py`, which returns a `Host`.
Adding a cloud is one new module and one changed import.

A deploy is a consequence of a green build: `ci` calls the `deploy` workflow, which applies the
playbook with `image_tag` set to that commit's sha. Never `latest`, so the box's state is a function
of a commit rather than of when it last pulled. `just deploy <sha>` is the recipe CI runs.

**The box holds no clone of this repo and no registry credential.** Ansible copies the one file it
needs, `compose.yaml`, from the control node, so the compose file and the image tag cannot come from
different commits. The images are public: a private registry would mean a classic PAT, and GitHub
has no API to mint one, so rotation could never be automated.

### Pulumi adopts, Ansible converges

The split is about which tool can run twice. `pulumi import` taught Pulumi about a box that already
existed, so every value in the program is pinned to what is there — a computed image id reads as a
changed `source_details`, which replaces the instance.

Bootstrap therefore does **not** use cloud-init, which runs once and can never converge. Docker,
Tailscale, the heartbeat and the reclamation defence are Ansible roles instead, so re-running the
playbook is always the way back to a known state.

Reachability is Tailscale, for you and for CI, which joins as an ephemeral tagged node. Serve
publishes the API over HTTPS on the MagicDNS name, so the app binds loopback, nothing listens on the
tailnet, and no domain is bought or baked in anywhere. Node key expiry is the one way to lose access
to the box; `infra/README.md` covers it.

## Security

- Admin is never publicly reachable. It has session auth, but it is still full CRUD over the entire
  archive. Its password is stored as an scrypt hash, so the plaintext never exists in `.env`, in
  `pulumi stack output`, in the Ansible variable file or in the box's environment. Production
  refuses to start without one configured.
- Postgres is never published in `compose.yaml`. The dev port binding lives in the override file.
- No registration endpoint, ever. Single user, seeded credentials.
- Never log request bodies for `/accounts/ClientLogin` — it carries the API password.
