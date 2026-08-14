# Phase 1 — feed ingestion

Poll feeds on a schedule, keep everything they give us, and read the result in Admin.

There is no read API and no UI in this phase, deliberately. The point is to get a corpus flowing and
then look at it, because most of the decisions after this one — how dedup should work, whether
extraction is needed per-feed or universally, what a ranked stream should even sort on — are
answerable from a few weeks of your own feeds and not answerable now.

## The spine

Three layers, and almost everything else follows from them.

```text
documents       what the network said           raw bytes, append-only
item_versions   what we understood it to mean   parsed rows, append-only
items           what we think exists            identity, mutable
```

Later work attaches to exactly one of them. Extraction and embeddings hang off `item_versions` —
derived, re-derivable, and an edit invalidates them for free with no cache-busting logic anywhere.
Cross-source dedup operates on `items`, growing a _story_ concept above them. Nothing needs to touch
`documents` again once it's written.

Two rules keep the layers honest.

> **Anything derivable from bytes we've stored can wait.** Only what we'd have to re-fetch from the
> network is urgent.

Embeddings, extracted text, search indexes, better parsing, fields nobody modelled — all derivable,
none lost by waiting. A feed document served on a Tuesday and gone by Wednesday is not. So the one
thing this phase must not get wrong is capture.

> **Ingestion writes `feeds`. Everywhere else it inserts.**

`items`, `item_versions` and `documents` are append-only to the poller — no `UPDATE`, no `DELETE`,
no exceptions. Nothing a publisher has ever served is edited in place, so a stealth edit or a
redaction is caught rather than lost, and read state is safe structurally because ingestion never
issues a statement that could touch it. A rule with a carve-out is a rule nobody can test; this one
is a single assertion.

Together they retire vectors, extraction and search from this phase, and dictate the item tables.

## Why no read surface

The candidates were a GReader-compatible API for NetNewsWire, or a native API plus a minimal web UI.
Both were rejected for the same reason: they are read-surface designs, and the information needed to
design a read surface doesn't exist yet. The greader analysis is preserved at the bottom, along with
the one rule that matters if it ever gets built.

Admin is not a good reading experience. It is a _cheap_ one — sqladmin gives full CRUD over every
column for a few dozen lines, and for the job of "is this data right?" it beats a polished UI,
because it hides nothing.

## Packages

```text
src/old_news/
  ingest/                 polling — runs on a schedule
    service.py            poll_feed(feed_id) — orchestration
    store.py              owns the append-only write invariant
    parser.py             feedparser boundary; nothing else imports it
    normalise.py          canonical URLs, and what counts as a change
    schedule.py           next_poll_at and backoff — pure, no DB, no clock
  subscriptions/          managing what we follow — runs when you say so
    service.py            add, unsubscribe, import, export
    opml.py               import and export
    discover.py           site URL → feed URL
  db/
    base.py               DeclarativeBase, naming convention, uuidv7 keys
    session.py            async engine and session
    models/               feed, subscription, document, item (+ item_versions)
    migrations/           alembic
  tasks/
    ingest.py             schedule_polls (periodic) + poll_feed
  api/
    admin.py              sqladmin, mounted as an ASGI sub-application
  passwords.py            scrypt hashing for the admin login
  config/
    ingest.py, admin.py
  __main__.py             argparse: serve | opml import/export | admin-password
```

`subscriptions/` is separate from `ingest/` because they are different jobs, not because feeds
appear in both. Polling is scheduled, touches every table, and runs unattended; subscription
management is operator-triggered, touches `feeds` only, and will have more callers than `ingest/`
ever does — a read surface, and greader's `quickadd` if that is ever built.

`store.py` exists because `ARCHITECTURE.md` rejects a repository layer, correctly, but "ingestion
appends, never overwrites" still has to live in exactly one place or the third caller violates it.
It is not a repository. It is the module that owns that rule.

`library/` — stream queries and read state — is deferred with the read surface. Writing pagination
and filtering before there is an API to serve is guessing.

## Schema

Five tables, no partitioning — it constrains the primary key, and there is nothing yet to partition.

### `feeds`

```text
id                    UUID PK, DEFAULT uuidv7()
url                   TEXT UNIQUE          the URL we fetch
site_url              TEXT                 <link> from the feed
title                 TEXT
description           TEXT
language              TEXT
categories            TEXT[]               the feed's own <category> elements
icon_url              TEXT
platform              TEXT                 from <generator> — "WordPress 6.4", "Ghost"
ttl_seconds           INT                  <ttl> / sy:updatePeriod; a hint schedule.py can use
hub_url               TEXT                 WebSub, if advertised — recorded, not used yet
etag / last_modified  TEXT                 conditional GET
last_polled_at        TIMESTAMPTZ
last_success_at       TIMESTAMPTZ
next_poll_at          TIMESTAMPTZ          indexed; the scheduler's only predicate
consecutive_failures  INT
last_error            TEXT                 what went wrong, in Admin, without opening Logfire
suspended             BOOLEAN              the poller giving up, not a choice
suspended_reason      TEXT
created_at            TIMESTAMPTZ
```

`platform` is the `<generator>` element — the publishing software, not the masthead. It is one
column, free at poll time, and it is what you group by when investigating which feeds churn their
guids, because platform migrations are what cause that.

`ttl_seconds` earns its place by feeding the scheduler. `hub_url` records something only available
at poll time: WebSub gives push instead of polling, which needs a publicly reachable callback, and
the app binds loopback behind Tailscale Serve. The subscriber is a later problem; capturing the hub
is not.

### `subscriptions`

```text
id          UUID PK, DEFAULT uuidv7()
feed_id     UUID FK UNIQUE
category    TEXT                       from OPML on import; flat, not a hierarchy
active      BOOLEAN
added_at    TIMESTAMPTZ
```

Following a feed is not the same fact as the feed existing, and the two were conflated on one row
until `disabled` had to mean both "I unsubscribed" and "this 404'd ten times running". Those want
opposite handling, and mixing them poisons the corpus question about which feeds actually break.

So `Subscription.active` is a choice and `Feed.suspended` is the poller giving up. Unsubscribing
leaves the feed and its entire archive in place, which is what makes re-subscribing reconnect to
history rather than start again.

One-to-one is a `UNIQUE` on `feed_id` rather than a shared primary key. Same guarantee today;
relaxing it later is dropping a constraint rather than replacing a key.

### `items` — identity, and nothing else

```text
id                UUID PK, DEFAULT uuidv7()
feed_id           UUID FK
guid              TEXT                   whatever the feed called it, verbatim
identity_key      TEXT                   the resolved key this item is recognised by
identity_source   TEXT                   'guid' | 'link' | 'hash'
first_seen_at     TIMESTAMPTZ
read              BOOLEAN
read_at           TIMESTAMPTZ

UNIQUE (feed_id, identity_key)
INDEX  (feed_id, first_seen_at DESC, id)
```

No column a publisher controls appears here — not cached, not pointed at. An article's identity
survives every edit, which is what lets read state, dedup group membership, extraction results and
embeddings attach to it without breaking the first time someone fixes a typo.

`identity_key`, not `guid_key`: the value is often not a guid, and "dedup" is about to mean
_cross-source_ dedup in phase 2. Two different things called dedup is a collision worth avoiding
now.

**There is no `current_version_id`.** Current is the tail of the version chain, which is derivable,
so storing it would be a cache of a fact the database already holds — and it would put a cycle
between the two foreign keys, since versions point back at items. Dropping it removes the cycle,
removes the nullable column the cycle would have forced, and leaves `read` / `read_at` as the only
mutable columns on the item side.

`first_seen_at` is the one column here that is technically derivable — it equals version 1's
`observed_at`, and uuidv7 encodes it in the key besides. It stays because it is written once at
insert and never changes, which is a different thing from a cache that tracks a moving value, and
because a plain queryable creation timestamp is worth more than the purity.

Reading current values is a relationship, not a column — the join condition lives on the model, so
it is written once:

```python
await session.execute(select(Item).options(joinedload(Item.current_version)))
```

`lazy="raise"` on it, so forgetting the option is an error rather than a silent query per row.
Measured on 20k items: `joinedload` 11 ms, `selectinload` 14 ms, an equivalent `DISTINCT ON` 9 ms —
so the relationship is for single items and small pages, and `store.current_versions()` does the
bulk anti-join the poller needs.

### `item_versions` — append-only

```text
id             UUID PK, DEFAULT uuidv7()
item_id        UUID FK
document_id    UUID FK                     the exact document this version came from
supersedes_id  UUID FK item_versions       NULL for the first; UNIQUE, so no forks
observed_at    TIMESTAMPTZ
title          TEXT
author         TEXT
url            TEXT                        as served
canonical_url  TEXT                        normalised — see below
summary        TEXT
content        TEXT                        as served
tags           TEXT[]                      the feed's own categories
enclosures     JSONB                       url, type, length — podcasts and images
comments_url   TEXT
published_at   TIMESTAMPTZ                 from the feed, if it has one
updated_at     TIMESTAMPTZ                 from the feed
content_hash   BYTEA                       over every column above, normalised

UNIQUE (supersedes_id)                     no two versions supersede the same one
UNIQUE (item_id) WHERE supersedes_id IS NULL   exactly one head per item
CHECK  (supersedes_id IS NULL OR id > supersedes_id)
INDEX  (canonical_url)
INDEX  (item_id, id)
```

Never updated, never deleted. The first version is written on sight, so the history is complete and
self-contained — reconstructing what a feed said on a given day needs no join against `items`.

**A chain rather than a version number**, so ordering is structural and every guarantee is a plain
constraint rather than a trigger. The `CHECK` is what makes `ORDER BY id` provably chain order —
uuidv7 is time-ordered, and each link must sort after the one it supersedes — which in turn makes
"revision 6 of 7" a window function instead of a recursive walk:

```sql
row_number() OVER (PARTITION BY item_id ORDER BY id)
```

That `CHECK` can reject a legitimate insert when two uuidv7 keys are minted inside the same
sub-millisecond tick. Polls are minutes apart so ingestion never sees it; re-deriving versions from
stored documents in a tight loop can, and retrying with a fresh key is the intended response.

`content_hash` covers **every** field the feed supplied, not just title and content. A redaction to
an author line, a quietly changed URL, a dropped tag — each produces a version. Hashing a subset is
how an archive silently loses the thing it exists to catch.

`canonical_url` is the cheapest possible input to cross-source dedup, and it was missing from every
earlier draft of this. Feed links carry `utm_*` parameters, FeedBurner proxies, inconsistent schemes
and `www` prefixes, and "do duplicates across feeds share a URL?" — a question this phase exists to
answer — cannot be asked without normalising first. Phase 1 does **syntactic** normalisation only:
strip tracking parameters, lowercase the host, drop the fragment. Resolving redirects needs network
fetches and arrives with `extract/`.

That index is also what catches guid churn: an unseen `identity_key` arriving with a canonical URL
already known for that feed means the feed migrated — a platform move, a domain change, a permalink
restructure. Count it and log it; don't auto-merge, because some feeds legitimately reuse a URL for
live-updating or roundup pages. How often it happens is a question for the corpus, and worth
cross-referencing against `feeds.platform`.

`identity_source` records which tier of the key won. It does **not** detect a feed changing its guid
_values_ — a migration that rewrites every guid still reports `'guid'`. What it tells you is which
feeds sit on the fragile `hash` tier, i.e. which are at risk. Fleet health, not debugging.

`tags` and `enclosures` are modelled rather than left to the document because they're what you'd
filter on soonest — tags are real ranking signal, and enclosures are an entire content type, since a
podcast feed is unusable without them. The long tail stays in the document and gets backfilled if it
turns out to matter.

### `documents` — the raw bytes

```text
id            UUID PK, DEFAULT uuidv7()
feed_id       UUID FK
fetched_at    TIMESTAMPTZ
status        INT                          HTTP status
body_hash     BYTEA                        sha256 of the raw bytes
body          BYTEA                        as received, before any decoding
headers       JSONB                        etag, last-modified, content-type, cache-control
parse_ok      BOOLEAN                      whether the parser of the day coped
parse_note    TEXT                         feedparser's bozo message, if any

INDEX (feed_id, fetched_at DESC)
```

Written when the body differs from this feed's **previous** document, not when it's globally unseen.
That distinction matters: a publisher reverting a redaction produces A → B → A, and deduplicating on
hash forever would record that the two states existed but not the order they happened in. Reverts
are rare, so the storage difference is noise and the timeline is worth having intact.

Called `documents` rather than `responses` because we do not store responses — 304s and unchanged
bodies write nothing, so a response log is exactly what this isn't. It is also the name that stays
true if bodies ever move to B2 and arrive by some other route.

The parser drops a great deal even after the additions above: typed link relations, `media:*`
thumbnails, source attribution on aggregator feeds, rights, `slash:comments` counts, iTunes
metadata. Chasing each into a column is the wrong fix. Keeping the document means every one of them
is recoverable, the whole archive can be re-parsed by a better parser later, and mis-declared
character encodings stay fixable because the bytes and the `content-type` are both still there.

Cost is bounded by conditional GET plus the hash: an unchanged feed writes nothing. At fifty feeds
that lands in the low hundreds of MB per year, and Postgres TOAST lz4-compresses `BYTEA` for free.
If it grows past comfort the escape is B2 — `infra/resources/storage_b2.py` already provisions the
bucket — or dropping bodies older than N months once the parser is trusted. Note that documents land
in `pg_dump`, so backups grow with them.

### One thing the chain does not enforce

Every feed having a subscription, and every version chain being reachable from its item, are both
mandatory-on-both-sides relationships. Postgres can't express those without deferred constraints, so
the application creates each pair in one transaction and the tests assert it.

### Why two histories

`item_versions` is derivable from `documents` by re-parsing, so rule one says defer it. It survives
that objection on one point: `items` needs current values _somewhere queryable_, and the only
alternatives are putting them on `items` and overwriting, or re-parsing the archive to answer a list
query. Versions are not a second history — they are where item data lives at all, and history is a
free consequence of never overwriting it.

The simpler design, if the join ever proves intolerable: current values on `items` by upsert, with
only _superseded_ values archived to `item_versions` in the same transaction. Same information, no
pointer, no join. Its worst case is a bad overwrite; this design's worst case is a stale pointer. A
`joinedload` makes the join cheap enough that this trade doesn't need taking.

### Why not a `responses` table

Splitting the HTTP event from the content — `responses` holding status, headers and timing, pointing
at a content-addressed `documents` — is the tidier modelling, and it is the wrong call here. It
writes roughly 876k rows a year at fifty feeds, almost all recording that nothing happened, and that
history already exists in two places: `feeds.last_polled_at` / `last_success_at` /
`consecutive_failures`, and a span per fetch in `fetch/client.py`. `ARCHITECTURE.md` settled this —
Postgres holds state, traces hold history.

The one thing it would uniquely answer, which document was live when, falls out of
`documents.fetched_at` ordering now that writes are change-from-previous rather than globally
deduplicated. The one real gap is durable _failure_ history, since traces expire and
`consecutive_failures` only knows about now. If that bites, it wants a small failure log, not a
response log.

## Ingestion

```text
tasks/ingest.py  ──►  ingest/service.py  ──►  fetch/   (HTTP)
                            │                  store.py  (all writes)
                            └───────────────►  parser  (feedparser)
```

**Scheduling.** A periodic task each minute selects feeds that are subscribed, not suspended and
due, and defers `poll_feed(feed_id)` — an identifier, never a URL, because procrastinate logs kwargs
at INFO and feed URLs carry API keys. Its own `ingest` queue so a backlog can't starve maintenance,
and `queueing_lock = f"feed:{id}"` so a slow feed can't stack up behind itself.

**A poll.**

```text
load feed
  → Fetcher.get(url, etag, last_modified)
  → 304?  bump the schedule, stop
  → body same as previous document?  bump the schedule, stop
  → write document      (before parsing — a body that crashes the parser is still captured)
  → parse
  → load the tail version of every item in this feed   (one anti-join, not one query per item)
  → per item:  unseen identity_key  → insert item + head version
               known identity_key   → hash differs?  insert a version superseding the tail
  → update the feed row
```

`feeds` is the only table that flow updates. Everything else is an `INSERT`, so `read` / `read_at`
cannot be touched by a poll even in principle. That is worth an explicit test — not of the values,
but of the statements — because it is the invariant the archive rests on.

**`parser.py`** is the only module importing `feedparser`, and it returns frozen dataclasses —
`ParsedFeed`, `ParsedItem` — carrying real tz-aware `datetime`s, with no `feedparser` type escaping.
`bozo` is a warning recorded on the document, not a failure: a great deal of the web's RSS is
malformed and parses fine anyway.

**Identity key**, in order: the feed's own guid → the link → `sha256(title|published|summary)`.
Record which one won.

**`normalise.py` decides what a change is**, and it is the hard part — the schema isn't. Feeds serve
rotating ad markup, cache-busting query parameters and reordered attributes, so a hash over raw
content fires on every poll and buries real edits under noise. Collapse whitespace, strip tracking
parameters, sort attributes. It owns URL canonicalisation for the same reason: both are "what counts
as the same thing", and they should agree.

Phase 1 treats this as measurement. Append versions, then look at what fraction are genuine edits.
That ratio defines the normalisation and cannot be guessed from here.

**Backoff** lives in `schedule.py` as pure functions over
`(interval, failures, new_item_count, ttl_seconds)`, so the policy is unit-testable with no database
and no clock. Exponential on failure, capped around a day; disable after N consecutive failures, or
immediately on 410 Gone.

**Things HTTP will do to you**, all cheap now and expensive to retrofit:

- A permanent **301** on the feed URL updates `feeds.url` — via `subscriptions/`, since retargeting
  a subscription is its job, not the poller's. Otherwise you follow the same redirect forever.
- **429 and 503** carry `Retry-After`. Honour it — feeds rate-limit, and ignoring it is how you get
  blocked.
- **Per-host concurrency.** Twenty feeds from one publisher polled at once is rude and looks like an
  attack. Keep worker concurrency low, or lock per host. This is the first place the missing
  _publisher_ concept bites; host-from-URL is enough for now.
- **Future-dated items.** Bad server clocks produce `published_at` next year, which poisons any
  sort. Clamp to `observed_at` and record that you did.

## Subscriptions and OPML

Import is not a nice-to-have. It is how twenty feeds get in without typing them into Admin one at a
time, which is otherwise the last step of this plan.

- **Import** reads `<outline>` elements, takes `xmlUrl` as the feed and the parent outline's `title`
  as `category` — flat, single value. Not a folder table; just don't destroy the information on the
  way in. Entries with only a site URL go through `discover.py`.
- **Export** regenerates the same file. The anti-lock-in guarantee, and it costs almost nothing to
  keep working from day one.
- **Discovery** — fetch a site URL, read `<link rel="alternate" type="application/rss+xml">`. Small,
  and import needs it anyway.
- stdlib `xml.etree` rather than a dependency; cap the file size, since ElementTree's expansion
  limits are not something to lean on.

Both are `__main__.py` subcommands with justfile recipes — `just opml-import feeds.opml`,
`just opml-export`. This phase has no API, and OPML is an operator action rather than a read
surface.

## Admin is load-bearing this phase

It is the only read surface, so it has to be real — but nothing is designed around it. It is
scaffolding for looking at the corpus, not the end state.

- sqladmin is a Starlette app mounted as an ASGI sub-application. Two things bite at that boundary:
  Litestar's mount appends a trailing slash to the forwarded path and sets no `root_path`, and until
  both are fixed every admin URL 307s to a location missing the `/admin` prefix. It also needs
  `itsdangerous`, which it does not declare.
- Never publicly reachable. It has session auth and it is still full CRUD over the whole archive.
- `__str__` on each model, so a foreign key renders as a headline rather than a UUID.
- Items are identity-only, so browsing content means looking at `item_versions`. That split is the
  schema working as intended, not something to paper over here.
- Keep `documents.body` out of any list view. A page of fifty rows each dragging a compressed feed
  document is how Admin becomes unusable, and it will happen by default.
- Login is a scrypt hash from `just admin-password`, never a password. The hash uses `:` as its
  separator because docker compose expands `$NAME` inside env values and would silently eat the
  salt. Production refuses to start unconfigured; local falls back to a development password with a
  warning on every boot.

## What the corpus is for

The deliverable is the data _and_ the answers to questions currently unanswerable. Worth writing
down after a few weeks:

- **Volume.** Items per day, per feed. Decides whether partitioning is real or theoretical.
- **Duplicate rate across feeds.** How often the same story lands from several sources, and what it
  looks like — shared `canonical_url`? identical titles? neither? This is the only thing that tells
  you whether dedup is a URL join, a title match, or genuinely needs embeddings.
- **Version churn.** What fraction of hash changes are genuine edits versus ad markup. Defines the
  normalisation, and decides whether version history earns its storage.
- **Real edits, when found.** What actually gets changed after publication. If this is interesting,
  it is a feature rather than bookkeeping.
- **`identity_source` distribution, and guid-churn hits.** How many feeds sit on the `hash` tier,
  and how often a known canonical URL arrives under a new key. Cross-reference `platform`.
- **Feeds per publisher.** How much the missing publisher concept would actually buy.
- **Content completeness.** What fraction of items carry full text versus a teaser. Decides whether
  `extract/` is universal or a per-feed flag.
- **Date sanity.** Items with no `published_at`, or one in the future, or wildly older than
  `observed_at`. Decides what a stream sorts on.
- **Document growth.** Actual MB/month, against the estimate above.

Phase 2 is chosen from that list, not from this document.

## Tests

`tests/unit/` — `parser.py` against fixture feeds: malformed, missing guid, duplicate guids within
one document, absent dates, future dates, CDATA, relative links, enclosures, Atom vs RSS 2.0,
mis-declared encoding. `schedule.py` across success, failure and recovery. `opml.py` round-trip.
`normalise.py`: the same article with rotated ad markup must hash equal, a one-word redaction must
not, and URL canonicalisation must be idempotent.

Check the fixture corpus in. It is a regression net for every parser change afterwards and it costs
nothing to keep.

`tests/integration/` — `poll_feed` against a real loopback server: fresh fetch, then 304, then a
changed body; OPML import with discovery against a second one. The ones that matter:

- An edit appends version 2; version 1 still holds the original text verbatim.
- A change to `summary` or `author` alone — not title or content — still produces a version.
- `read` survives an edit, because no statement in a poll can write it.
- An unchanged body writes no second document; a reverted body writes a third.
- Across a full poll, `feeds` is the only table updated. Assert the statements, not the values — the
  invariant is about what ingestion is capable of, not what it happened to do.
- A second subscription for one feed is rejected by the database, not by the service.
- Unsubscribing leaves the feed and its archive; re-subscribing reactivates rather than duplicating.
- `Retry-After` is a floor, not a target: a short one loses to our own minimum, a long one wins over
  the backoff policy, and an HTTP-date one falls back to the maximum.

No mocked Postgres, no stubbed HTTP transport. `fetch/` is already tested against a real server on a
loopback socket and this follows it.

## What got built

All of it, with 133 tests. Worth recording what the work itself turned up, because none of it was
visible from the design:

- **The ORM changed mid-phase.** Piccolo has no way to express a derived join on a model — no
  relationships with custom conditions, no reverse lookups, no computed attributes — so
  `current_version` would have had to be a database view or a repository, and this codebase rejects
  the second. SQLAlchemy expresses it directly. The move also cost a day to a segfault: 2.0.x's C
  extension isn't free-thread safe, CPython 3.14t re-enables the GIL to load it and then crashes
  inside traceback printing, which hides the real error. 2.1.0b3 is clean and is pinned as a
  prerelease.
- **Database telemetry was silently off.** `opentelemetry-instrumentation-sqlalchemy` pins
  `sqlalchemy<2.1` and, against 2.1, logs a `DependencyConflict` and emits nothing. Both it and the
  asyncpg instrumentation are registered: asyncpg carries statements today, and the richer ORM span
  appears on its own when that support lands.
- **`max(uuid)` does not exist in Postgres**, and adding it is not worth it — measured at 26x the
  buffer reads of `NOT EXISTS` on the bulk path for 0.06 ms on single lookups.
- **Postgres does not index foreign keys.** `item_versions.item_id` had no index at all.
- **`$` is unusable in an env value.** Docker compose expands `$NAME` inside it, which ate the salt
  out of the admin password hash and produced a hash that could never verify, with no error.
- **feedparser maps `updated_parsed` onto `published_parsed`** when the former is absent. "When the
  publisher says it changed" is not "when it was published", and the version chain depends on the
  difference.

## Deferred, with the reasoning kept

**A read surface.** Native API + web UI, or GReader for NetNewsWire. Decided in phase 2 from the
corpus.

**`library/`** — stream queries and read state. Lands with whatever consumes it.

**A `publishers` table.** Several things want it: multiple feeds under one masthead, per-publisher
politeness, publisher-level ranking signal, and cross-source dedup, which is the whole point of the
app. Host-from-URL covers the immediate need, and the corpus should shape the real thing rather than
this document guessing at it.

**Embeddings and search indexes.** Both derivable from stored bytes, so both free to defer, and both
expensive to commit to early. An `embedding VECTOR(n)` column needs `n`, which needs a model you
haven't chosen; guess 1536, pick 768 later, re-embed everything anyway. It also needs a decision
about _what_ gets embedded — title, summary, or extracted body — and extraction doesn't exist yet,
so embedding a teaser today is work you redo. Same argument retires the BM25 index: no query surface
to serve.

**Per-item processing state.** `extract_status` / `extract_error` / `extracted_at` on `items` is the
wrong shape — repeat that triple for embedding and enrichment and the table has forty columns. It's
`item_processing(item_version_id, stage, status, error, attempts, updated_at)`, one row per stage.
Keyed on the version, not the item, so an edit invalidates derived work automatically. Worth noting
the queue won't cover this: procrastinate deletes successful jobs and prunes failures after a week,
so "which items never got extracted?" is unanswerable from it by design.

**Retraction detection.** An item disappearing from a feed is interesting for an archive that cares
about redactions, and it is derivable from `documents` — the key stopped appearing. Rule one
applies: no column, no write amplification, recoverable whenever it becomes worth asking.

**WebSub subscriber.** Needs a publicly reachable callback; the app binds loopback behind Tailscale
Serve. `hub_url` is captured now so the option stays open.

**Folder hierarchy.** OPML nesting flattens to `feeds.category`. A tree is a read-surface concern.

**Partitioning.** Forces the partition key into the primary key and every unique index. `documents`
is likeliest to want it first; revisit against the volume numbers above.

**Splitting read state out.** It sits on `items`, which is narrow by construction, so the row-width
argument that would have forced a split is already answered by the version table.

**GReader.** Still the fastest route to a good native mobile client, and NetNewsWire is the target
to conform to precisely because it's open source — you read its client code instead of guessing
which of the protocol's undocumented corners it needs.
[FreshRSS's implementation](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)
is the de-facto spec; Google published nothing normative.

The argument against is that the protocol cannot express this app: no vocabulary for dedup groups,
ranked streams, or archive search, so it surfaces the generic-feed-reader half and none of the half
this project exists for.

If it is ever built, one rule: **greader gets its own tables, never a column on a core one.** Its
64-bit item id becomes

```sql
greader_item_id (
  item_id   BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  item_uuid UUID UNIQUE REFERENCES items(id) ON DELETE CASCADE
)
```

populated by a trigger created in the same migration, so removing the feature is `rm -r` plus one
`DROP TABLE`. Deriving that id from the UUID instead — truncation or hashing — leaves about 62
usable random bits and a birthday collision around one in ten million items, which silently welds
two articles' read state together. Not worth it when a mapping table is free.
