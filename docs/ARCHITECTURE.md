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
  ui/                what the reading UI asks for: a river, an article, the archive
  kindle/            the weekly periodical: what goes in it, and getting it there

  # edges
  api/               Litestar app, routes, admin mount
```

Everything is a package, each owning its own frozen dataclasses. The groups above are comments, not
directories — the layering is real but flat on disk, because a package that has to be reached
through a parent is harder to move than one that doesn't.

`tests/unit/test_architecture.py` asserts this list against the filesystem, so growing a new
top-level package fails in the diff that grows it. That is the point: sprawl is cheapest to argue
about at the moment it appears.

### The tree governs `src/old_news/` and nothing else

The reading UI is a SvelteKit client in `web/` — a sibling of `src/`, not a package under it
(`docs/PHASE-3.md`). It is a different language with different conventions, and the rules in
CLAUDE.md — one library per package, one transaction per function, services holding the logic — are
about Python and do not translate. Making `web/` a carve-out inside them would weaken rules that
currently have no exceptions.

The contract between the two is generated rather than written: Litestar publishes OpenAPI at
`/schema`, and the client's types come from it, so the two halves cannot drift quietly. `api/`
remains the only thing `web/` talks to, which is the same direction rule as everywhere else.

`ui/` is the Python half of that pairing and stays inside the tree: it is a service like any other,
holding the queries the screens are made of. It renders nothing. The split is what stops the river's
ordering, its keyset cursor and what counts as opened from being written again in TypeScript where
no test would reach them.

Inside it, `entries.py` holds the row shape and the keyset every list of items shares, and the three
screens are the ways of choosing which rows: `service.py` the river, `archive.py` a shelf,
`search.py` what the words reach. A list is one page of an ordered query in all three cases, so
`Listing` is what all three return and one component renders them.

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
`ItemVersion.feed_capture`, `ItemVersion.feed_extraction`, `ItemVersion.page_extraction`. Each is
`viewonly` with a `primaryjoin` doing the anti-join, and each is `lazy="raise"` so a forgotten
`joinedload` fails loudly instead of firing a query per row.

Both extraction bridges are per source rather than one "latest reading", because that is the
comparison `reading_body` makes: a superseded extractor's longer output must not beat the current
one's. `has_feed_text` is the same care in the other direction — it reads the newest capture, not
any capture, so the sweep never offers a version `pending_feed` will return nothing for.

Two of them are deliberately not scoped to the head version. `Item.current_extraction` and
`Item.reading_body` span the whole chain, because an edit makes a new version the head and its page
waits out the settle window before being fetched — head-scoped, they would blank an article for an
hour every time a publisher touched it. `ItemVersion.reading_body` answers the narrower question
about one version, which is what a history view wants.

`reading_body` is a `hybrid_property`, so a river can select and sort on it without loading every
body into Python. That puts one policy — which reading a reader gets — in the model layer rather
than a service, which is the exception to the rule below and is why it is written down here. It is
one ordered subquery over the newest reading per source rather than a `CASE` comparing two: two
spellings of "which one won" is what the column it replaced already cost us. `Item.reading_body`
raises in Python for the reason `Feed.consecutive_failures` does — it only exists as SQL, and
answering from a half-loaded row would be a stale answer.

Length used to decide that on its own, and it was wrong at both ends. A page whose article the
extractor missed still hands back a few hundred characters of template, which beat a feed item that
was a comic and a caption. And a feed that syndicates the whole piece but drops the subheadings beat
the page that kept them, by a margin of about fifty characters in eight thousand. So the ordering
asks four questions instead: does this carry the whole article — prose, and within a share of the
longest reading held; failing that, is it prose at all; failing that, which kept the most headings,
quotes and pictures, since that is all a comic has; and only then, which is longer. The preference
still breaks a tie. The share and the character floor sit next to it in `db/models/item.py`, because
they are what "the same article told twice" means rather than a measure of extraction quality — that
one is `judge()`, and its thresholds are config.

### The periodical fetches nothing, and calibre only converts

`kindle/` builds a weekly book out of what the archive already holds. Nothing in it makes a network
call except the one that posts the finished thing to Amazon.

That is the whole reason it exists. The obvious way to get a Kindle edition is a calibre recipe over
a feed, and that is what the arrangement it replaced did — `use_embedded_content = False` and
`auto_cleanup = True`, so calibre re-fetched every article and ran its own readability, throwing
away a better reading that was already stored and crawling publisher hosts outside everything
`politeness/` and `robots/` are for. Here the recipe reads a manifest the app wrote and every
article is a local file, so calibre is asked for the periodical structure and the format and nothing
else.

Two things about it are not guessable from the code. **The cover is SVG**, because it carries the
issue's date and tally and so cannot be a checked-in asset — and Pillow belongs to `extract/`, where
a nameplate is not a rendition of anything held. **It is rasterised inside the recipe**, after
`must_use_qt()`, because calibre rasterises a downloaded cover before it has a `QGuiApplication` and
Qt's font machinery needs one. The masthead is calibre's own: a supplied one bought nothing, and the
synthesised one carries the date.

Expiry is the other half of the same idea and is deliberately not a job. A window on the
subscription and a clause in the river's `WHERE` means widening one is instant rather than a rewrite
of the archive, and the cutoff lands on the leading column of `ix_items_river`, so it costs less
than no cutoff at all.

That window is then read a third time, by the sweep that fetches body images. Whether a picture is
worth holding is the same question as whether the article is — a long window, or a book to appear in
— and the wire is where the volume is: measured on this archive, the short-window feeds are about
88% of the ongoing image bill and none of what gets read twice. Leads stay unconditional, because a
card or a page with a hole in it is a different problem.

### The archive is a contents page, not a longer river

Lifting the cutoff off the river was the first version of the archive and it was the wrong screen.
The river answers "what is new", which wants no navigation at all; an archive answers "where was
that thing" and "what did this publication run that I never got to", and one reverse-chronological
list answers neither. It also grows without bound — at present rates six figures inside a year, over
half of it wire — so the list has no end to reach and no landmark to come back to.

So the archive lands on a contents page instead, and everything off it is bounded. Publications are
shelved by tier, because the tier is already the judgement of whether a back catalogue is worth
walking, and the wire's arrives folded. Months carry their counts, so a shelf too big to enter says
so before you enter it. A dropped feed keeps its shelf: unfollowing stops a poll and takes nothing
away. Sections are absent on purpose — they are how you skim what is new, and a third axis crossed
with the other two is a screen nobody can hold in their head.

A shelf is `first_seen_at` between two instants, or one `feed_id`, or both, which is what
`ix_items_river` and `ix_items_feed_first_seen` are already built for. Months are grouped in the
reader's own zone and turned into those two instants in Python, so the label a shelf carries and the
rows it holds cannot disagree about where midnight was.

### Search is two indexes, because the text is in two tables

A headline is on `item_versions` and the article on `extractions`, and BM25 wants its fields side by
side. Putting them there means a third table copying what the first two already say, kept in step by
a task — and a copy of the archive that a task maintains is a copy that will drift, silently, in the
direction of the reader not finding something. Two indexes on the two real columns are maintained by
Postgres on every write instead, so nothing is ever stale and a backfill needs no rebuild.

The cost is that scores from the two are not comparable, so nothing pretends otherwise: a headline
match outranks a reading match and BM25 only breaks the tie inside each group. In practice the
reading carries the headline anyway — trafilatura keeps it, which is why the book has to strip it —
so the body index alone reaches almost everything and the title index is a boost rather than the
only route in.

Two smaller decisions. Terms go through `paradedb.match` rather than the query-string form, so a
colon in what was typed is a word and not a field name and a stray quote is not a parse error. And
every word is required: either-of-them is what makes a search over a hundred thousand rows useless,
and it makes the match count a number worth showing. Results page by depth rather than by keyset,
because relevance is not a column there is an ordering to cut on.

### The extractor writes markdown trafilatura will not

Two things get done to trafilatura on the way past, both in `extract/article.py` and both because
the alternative is a reading that lies. Quoted blocks are marked before the tree goes in, since
trafilatura's markdown drops the mark entirely and a quotation then arrives as the author's own next
paragraph — about one page in ten carries one. And a feed fragment trafilatura returns nothing for
gets taken at face value instead, because a fragment is the publisher's own payload rather than a
page to find an article inside: an item that is a picture and a caption has nothing to select and
everything to keep.

Marking the way in rather than the way out means the tree has to be parsed here, which means
matching the parser trafilatura loads a string with. Its heading pass retags a node's children and
raises outright on a comment, so a tree carrying comments crashes an extraction that a string of the
same bytes survives.

One upstream defect is worth knowing about: lxml's free-threaded build asserts when it releases a
write lock on a tree it is collecting, on a minority of real pages. It is raised in a destructor and
reproduces on stock trafilatura with a plain string, so nothing comes out wrong, but it is why
`pyproject.toml` carries a narrow `filterwarnings` ignore rather than a blanket one.

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

Extraction is not on that chain, deliberately. It is six sweeps of its own on their own queue, each
finding work by what the archive is missing rather than by what a poll just wrote:

```text
tasks/extract.py ──► extract/due.py      what has no page       ──► extract/capture.py
                 ──► extract/feed.py     what has no feed text  ──► extract/feed.py
                 ──► extract/service.py  what has no reading    ──► extract/article.py
                 ──► extract/images.py   what has no picture
                 ──► extract/encode.py   what has no rendition
```

All six defer through `tasks/sweep.py`, which is the one place the queueing lock, the host lock and
the crawl-delay stagger are spelled.

A failing extractor cannot fail a poll, retries are independent, and re-capturing a five-year-old
article runs down exactly the same path as capturing one that arrived a minute ago.

And for a request:

```text
api/routes/reading.py        ──►  ui/service.py             ──►  db/
api/routes/archive.py        ──►  ui/archive.py, ui/search.py  ──►  db/
api/routes/subscriptions.py  ──►  subscriptions/service.py  ──►  fetch/, db/
```

A service never imports from `api/` or `tasks/`. That's the only direction rule, and it's what keeps
the same logic reachable from both a worker and an HTTP handler.

Feature packages still to be built: `enrich/`, `backfill/`, `library/`.

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

Migrations run on psycopg, not asyncpg. Nothing about them wants a loop, and `alembic_utils`
livelocks under an async env — the autogenerate that never finishes there takes a second against a
sync connection.

`alembic_utils` is installed and deliberately unwired. Two things to know before registering
anything with it. It treats its registry as the whole truth for every entity in the schemas it
watches, so on this shared schema it proposes dropping all of procrastinate's functions and triggers
unless `include_object` scopes it to views. And it learns which schemas to watch from the entities
you register, so it cannot notice the removal of its last one without being handed `schemas=[...]`
explicitly.

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

**A counter beside the thing it counts is a second copy.** `feeds` used to carry
`consecutive_failures`, `last_error`, `suspended` and `suspended_reason`, all maintained by hand on
every poll. They are gone. `feed_polls` records one row per poll and `Feed.consecutive_failures` is
a correlated subquery over it, so the number cannot disagree with the log, and the log is not
overwritten by the next poll the way `last_error` was. `page_captures` needed no new table for the
same job: it already wrote a row per attempt, so "how many times has this refused, and when" was
always a query.

Both derived properties are `hybrid_property` with an expression and a Python getter that raises —
they exist only as SQL, so `select(Feed.consecutive_failures)` works and reading it off a loaded row
fails loudly instead of returning a stale zero. The subqueries alias and `correlate_except`
explicitly: both halves select from the same table, and without it SQLAlchemy folds the inner
aggregate into the outer `WHERE`, which Postgres rejects.

**Where a threshold lives decides whether changing it works.** Giving up on a feed after N failures
is our policy, so it is applied in `due_polls` beside the setting that defines it, and lowering the
number takes effect at once. `Feed.gone` — the publisher answering 410 — is their statement, needs
no threshold, and reads off the log. Those were one column called `suspended`, which is why changing
the limit used to leave rows stamped with the old one.

**Everything else** is raw DDL in a revision: `op.execute` is how a column gets backfilled and how
the seed `training_rules` get in.

### Stored bodies are compressed, sometimes against a dictionary

`db/bytes.py` and `db/dictionaries.py` are the only modules that reach for `compression.zstd`.
Everything stored as bytes — feed documents, the item text carved out of them, article pages — goes
through it at one level, which is config rather than a constant.

Bodies that share a template compress about twice as well against a dictionary trained on their own
kind: feed documents 88 KB to 44 KB. Article pages gain less, 47 KB to 39 KB. What counts as a kind
is a `scope` — `feed_document`, `feed_item`, `host_page` — beside exactly one of `feed_id` or
`host_id`. Two of those share a feed and are still different scopes: whole feed XML and the HTML
fragments inside it have almost nothing in common, so a dictionary trained on one leaves most of the
win on the other unclaimed. Reusing it would be correct, because `train()` measures against a
held-out sample; it would just be worse.

What decides whether a dictionary is any good is how many samples it saw, not how big it is. Eight
buys 16%, twenty-eight buys 50%, and against held-out pages a 110 KB dictionary beats 512 KB, 1 MB
and 4 MB on every host tried. So the training sweep runs hourly rather than nightly: a scope without
one is storing at twice the size it needs to, and nothing already written is rewritten to fix that
later.

Three things make this safe to have done:

- **A frame names its own dictionary.** `get_frame_info(body).dictionary_id` is 0 or an id, so
  reading never depends on remembering what wrote it, and reading with the wrong one raises rather
  than returning plausible rubbish.
- **Nothing is ever rewritten.** A dictionary is immutable and outlives being current, because every
  body compressed against it stays that way. `documents.dictionary_id`,
  `feed_captures.dictionary_id` and `page_captures.dictionary_id` are foreign keys, so Postgres
  refuses to drop one still in use and it cannot go missing from a dump that holds the bodies.
- **No dictionary is always correct.** A scope with too little to learn from — fewer than
  `storage.dictionary_min_samples` bodies — stays on plain zstd. That is the cold start and the
  fallback.

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

### Backing off is the same arithmetic everywhere

`politeness/backoff.py` holds it: a `Policy` of four numbers and pure functions over it. A feed, an
article page and an image are refused in the same ways and so wait in the same shape; only the
numbers differ, and those come from config. `ingest/schedule.py` keeps what is genuinely a feed's
own — the `<ttl>` floor and the busy/idle drift — and delegates the failure half.

It carries two spellings of one formula. Sweeps pick their own work, so a backoff has to be
expressible inside a `WHERE` clause: filtering in Python after a `LIMIT` would silently shrink every
batch. `due_at` is the SQL form, and a test compares its numbers against the Python one across a
range of failure counts rather than trusting that two copies stay in step.

### A host refusing everything is one fact, not one per article

Medium answers 403 to every article page it serves, to any user agent, from any address. Backing off
per version leaves as many clocks as there are articles, all still knocking — 397 requests against 9
URLs in the 48 minutes before this was noticed. `extract/breaker.py` counts a host's recent captures
instead, and once the run of failures passes a threshold the fetch is skipped.

Two things make that safe. A status about a URL rather than a publisher — 404, 410 — is stepped over
rather than counted, or a handful of dead links would shut out a site answering everything else. And
a breaker that stops attempts freezes the window it reads, so it would never reopen: one probe per
interval is let through, purely to find out whether the refusal still stands.

Skipping writes no `page_captures` row. Deciding not to fetch is not an attempt, it matches what the
two robots checks beside it already do, and a row would poison the window the breaker reads.

### Feed text and page text are the same kind of object

Both are a reading of stored bytes the network handed over, so both are rows in `extractions`,
stamped with the extractor that produced them, derived and disposable. And both name the artefact
they read: `feed_captures` and `page_captures` sit either side of an `item_version`, one row per
version on the feed side and a log of attempts on the page side.

The asymmetry that made this hard is gone in stages. First the readings became one table. Then the
feed side got its artefact: feed text used to sit inline on `item_versions.content`, uncompressed
and with no record of what parsed it, so "which one do I read, index, embed" had no clean answer.

A feed capture is a materialisation, not a network event. The raw archive is `documents.body` and
the fetch that produced it is already in `feed_polls`, so there is no status, host or outcome on it
— what there is instead is `parser_version`, which makes re-carving after a feedparser bump a sweep
over stored documents rather than a loss. It holds content-or-summary, whichever the feed served,
which is what closes the hole where a summary-only version got no reading at all.

Captures deliberately do not become polymorphic. `page_captures` is a log of attempts that can fail,
`feed_captures` is a carving that cannot fail at all, `image_captures` is content-addressed and
shared across articles. A shared base would carry `outcome` where it is meaningless, or shrink to
four columns and buy a join.

Joined-table inheritance for the readings, after two attempts without it. `Extraction` is the base
and holds what every reading has; each child holds the capture it read, and `PageExtraction` also
holds what the page claimed about itself. So no column is meaningless for half the rows, and the
check constraint tying `page_capture_id` to `source` is gone: it existed only to hand-roll the
invariant inheritance states structurally.

The first two designs were wrong in opposite directions. Inheritance over the original table would
have produced subclasses whose only difference was which columns were dead, because the table was
doing four jobs. Splitting those jobs without inheritance left one nullable foreign key and a 1:1
sibling table, which is joined-table inheritance with worse parts. The decomposition had to come
first.

`FeedExtraction` earns its keep by not being the default. A bare `Extraction` meaning "feed" by
omission is the same overload as a column that means two things depending on the row, and the base
declares no identity, so `source` being NOT NULL makes the database refuse a reading that will not
say which kind it is.

`title` stays on `item_versions`, with both urls, because `training.blocked()` matches on them in
the `WHERE` of `due_captures` — before anything is fetched. Moving a title to an extraction would
make a block unevaluable on a version whose extraction sweep has not run yet, and the obvious fix,
extracting inside the poll, is ruled out: a failing extractor must not fail a poll.

A page reading claims metadata; a feed reading does not. On a fragment `extract_metadata` returns
the first heading inside the body — "Support Bellingcat", "Today's links" — because there is no
`<head>` to read a claim from. The feed states its own title and author, and those are on the
version: append-only, unrecoverable if lost, which is the opposite of a claim that can be
re-derived.

**A verdict is not a measurement.** `char_count`, `paragraph_count` and `link_density` are stored
because they are pure functions of `body` and cannot go stale. `ok` and `note` were deleted because
they were a verdict against `min_body_chars` and `min_paragraphs`, which live in config — so a
stored answer is wrong the moment either moves and says nothing about it. Twenty-five of 1058 rows
were already in that state. Same reasoning that removed `feeds.suspended`: a threshold judgement
belongs where the threshold is.

**`feed_body_ratio` was a symptom.** It existed only because the feed reading was not a row you
could join to. Both are rows now, so the ratio is `page.char_count / feed.char_count` across one
table — a query, not a column, and one that cannot disagree with either side.

### A refusal is a fact about how we asked

`page_captures.capture_policy` records the way a page was asked for, and the capture sweep counts
only the attempts made the way it asks now. So improving the asking — the `www.` retry, the agent we
send, how redirects are handled — forgives what came before it, without deleting a row.

That is `extractions.extractor_version` again, and deliberately so: bumping the extractor already
makes the whole archive due for re-extraction, and "the code changed, so old conclusions no longer
bind" is one idea, not two. The first version of this was a timestamp on `hosts` doing double duty,
which was a second mechanism for the same thing on a table that had no business holding it.

It matters because without it the fix cannot reach the articles it was written for. A publisher
whose apex has no DNS record burns through the retry limit in minutes, and the retry that would have
worked only ever runs on a version the sweep still selects. Fifteen articles here were in exactly
that state. `hosts.requires_www` stays, doing only its own job: which name to ask for next time.

### A queueing lock collision is not an error

`queueing_lock` means "only one of these may be waiting", but procrastinate reports the collision by
raising `AlreadyEnqueued` from `defer`. Unhandled in a sweep, that ends the sweep and silently
leaves every remaining item undeferred — feeds stop being polled and nothing says so except `failed`
climbing in the queue gauges. `tasks.tracing.defer_unless_queued()` is what both sweeps use instead,
and the skips are counted rather than thrown.

This matters more now than it used to: jobs wait on a per-host lock, so one still sitting in the
queue a minute later is ordinary rather than a sign of trouble.

### One worker per queue

`run_worker_async` used to be called once with no arguments, so every queue shared one pool of slots
and the queue names were decoration. The roadmap called this out before it bit: re-reading the
archive runs on the same worker as the polls keeping it current.

Now one worker per queue, each with its own concurrency, from `WorkerSettings.concurrency`. A few
thousand queued extractions can fill `pages` without touching what `ingest` has. Missing a queue
there means nothing serves it and its jobs sit at `todo` for good — which is how `default` (the
heartbeat, the nightly maintenance) was found unserved the first time this was written, so a test
compares the configured set against the queues tasks declare.

Signals are handled once for the process rather than per worker: `add_signal_handler` replaces
whatever was registered before it, so letting each worker install its own would leave only the last
one able to hear SIGTERM.

It isolates slots, not CPU. Extraction is synchronous work in the event loop, so a large page still
delays whatever else that process was going to do. Separate worker processes are the escalation if
polls start lagging behind their schedule; the queue split is what makes that a deployment change
rather than a code one.

#### Winding down is graceful, and therefore unbounded

Setting the stop event cancels each worker task, which is procrastinate's documented way of asking
one to stop. It shields its own run loop from that cancellation and instead sets a stop flag, so the
worker drains its in-flight jobs and its 5s and 10s pollers notice only between sleeps. Nothing
bounds the total: `shutdown_graceful_timeout` is left unset, and a wind-down measured over a minute
on the free-threaded build.

Neither `compose.yaml` nor the systemd unit sets a stop timeout, so Docker's default 10 seconds
applies and a worker that has not finished by then is killed rather than stopped. A job killed that
way is left at `doing` until `stalled_worker_timeout` reclaims it, where one abandoned by a bounded
shutdown would not be. Passing `shutdown_graceful_timeout` to `run_worker_async` is the fix, and the
number is a real tradeoff — how long to let a capture finish against how long to hold a deploy — so
it wants choosing rather than defaulting.

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
