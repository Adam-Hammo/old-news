# Scope: feed captures

Give the feed side the same shape the page side already has, and get the article text off
`item_versions` while doing it.

## Where this came from

`6d90aa5` made extractions name the artefact they read. `PageExtraction` points at a `PageCapture`;
`FeedExtraction` points at nothing and reads `item_versions.content` directly. That asymmetry is why
the feed text sits uncompressed on the core table, and why a version with only a summary never gets
extracted at all.

## The shape

```text
item
  └── item_version            identity, chain, and what selection filters on
        ├── feed_capture      the item's text as the feed served it   → feed_extraction
        └── page_capture      the article page as served              → page_extraction
```

An `item_version` is a distinct observed state, not a point in time — it exists because the content
hash changed, and `supersedes_id` chains them. One feed capture per version; many page captures per
version, including the visits that never sent a request.

## Decisions already made

Do not re-litigate these.

- **A feed capture is a materialisation, not a network event.** The raw archive is `documents.body`.
  A feed capture is the text `_body()` chose out of it, compressed, stamped with the parser version
  that chose it. So no `status`, `host`, `error` or `outcome` — the network event was the document
  fetch and it is already recorded.
- **It holds content-or-summary**, whatever the feed served. That is what closes the hole where a
  summary-only version gets no extraction, and it is what lets `reading_body` stop comparing against
  a raw column.
- **Captures do not become polymorphic.** `page_captures` is a log of attempts that can fail,
  `feed_captures` is one row per version that cannot, `image_captures` is content-addressed and
  shared across articles. A shared base would carry `outcome` where it is meaningless or shrink to
  four columns and buy a join.
- **`title` stays on `item_versions`**, with both urls. `training.blocked()` matches `TITLE_PHRASE`
  and `URL_PATTERN` in the `WHERE` of `due_captures`, before anything is fetched. Moving title to an
  extraction would make a block unevaluable on a version whose extraction sweep has not run. Running
  feed extraction inside the poll would fix that and is ruled out: a failing extractor must not fail
  a poll.
- **`content` and `summary` move off `item_versions`.** Nothing user-facing reads either — neither
  appears in admin.
- **Search will index `extractions.body`**, not the captures.

## Order

Reading must stop touching `content` and `summary` before the columns go.

### 1. `feed_captures`

Mirror `PageCapture`'s compression path, not its columns.

- `item_version_id`, unique **with** `body_hash` — not on its own. Nothing updates an append-only
  table, so re-materialising after a parser bump has to be able to insert. Same bargain
  `ImageCapture` makes with `(url_digest, body_hash)`: identical bytes conflict and the insert does
  nothing, different bytes get a row.
- `document_id` — which document it was carved from
- `body` `LargeBinary`, `body_hash`, `dictionary_id` FK
- `parser_version` `String(32)` — `feedparser.__version__` plus a rules revision, same shape as
  `article.extractor_version()`. This is the provenance `item_versions` never had;
  `documents.parse_ok` admits the gap in its own comment and does not close it.
- `captured_at`

### 2. A third dictionary scope

`ZstdDictionary` has `CheckConstraint("(feed_id IS NULL) <> (host_id IS NULL)")` and unique on
`(dict_id, feed_id, host_id)`. Item text is feed-scoped _and_ distinct from feed documents, so it
collides.

Do not reuse the feed's document dictionary. It was trained on whole feed XML; this is HTML
fragments. `train()` measures against a held-out sample so it stays correct, but it leaves most of
the win unclaimed.

Add a `scope` discriminator — `feed_document` / `feed_item` / `host_page` — with a `one_of` check
constraint, and widen the unique constraint to include it. Then `feeds_wanting_a_dictionary` /
`feed_samples` / `store_for_feed` need item-text siblings, and `train_dictionaries` gains a third
loop.

### 3. Populate captures

A sweep, not a poll side effect: re-materialising after a feedparser bump should be free, same
argument as capture being a sweep. `due_feed_captures` over head versions with text and no capture
at the current parser version.

### 4. `FeedExtraction` grows up

- gains `feed_capture_id`
- gains its own `__tablename__` — it deliberately has none today
- `pending_feed` reads the capture and `expand()`s it, exactly as `pending` does for pages
- `due_feed_extractions` selects versions with a capture and no current extraction, same shape as
  `due_extractions`

### 5. Reading

`reading_body` becomes `fullest(feed extraction, page extraction)`. `ItemVersion.feed_body` goes.
Both `Item.reading_body` and `ItemVersion.reading_body` change; `Item.reading_body` currently
reaches `feed_body` through `_current_version_join()`.

### 6. Drop the columns

Create, backfill, drop. Online-safe, unlike `ALTER COLUMN TYPE`, which rewrites the table under
`ACCESS EXCLUSIVE`.

The backfill cannot live in Alembic: `dictionaries` is async Python and Alembic's env is sync
psycopg. Use a `__main__` subcommand or a procrastinate task that batches.

## Traps

- `tests/unit/test_architecture.py` ratchets docstring and comment budgets. They only go down. Do
  not raise one.
- Migrations run on psycopg. `alembic_utils` is installed and deliberately unwired — read the notes
  in `ARCHITECTURE.md` before registering anything with it.
- `fingerprint_of` and `identity_of` hash the in-memory parsed item at ingest, not the columns, so
  change detection and identity are unaffected. Verify rather than assume.
- `db.bytes` owns zstd. `pyproject.toml`'s `banned-api` and `per-file-ignores` are the
  library-ownership list.
- A `LargeBinary` in a sqladmin list view is what made `documents` unusable. Check `admin.py` when
  adding the new model.

## Indexes

Audit the capture tables as part of this, not after. Two specific things:

**There are two spellings of success and the partial index is built on one of them.**
`PageCapture.succeeded` is `status BETWEEN 200 AND 299`, and `ix_page_captures_succeeded` is partial
on that same predicate. `host_failures` instead counts `outcome = 'ok'`. They agree today only by
construction — `_outcome_for` sets `OK` from `response.ok`, which is the same range. That is the
duplicate-definition shape that came off `consecutive_failures`, and it should collapse onto
`outcome`.

The trap: a partial index only serves a query whose predicate implies the index predicate. Change
`succeeded` to `outcome = 'ok'` without changing `postgresql_where` to match and Postgres silently
stops using the index — `_latest_capture_join`, `due_extractions` and `settled` all lean on it.
Change both together, and confirm with `EXPLAIN` rather than assuming.

**`ix_page_captures_host_fetched` does not cover what reads it.** It is
`(host_id, fetched_at DESC, outcome)`, but `host_failures` also filters
`capture_policy = CAPTURE_POLICY`, so that is a recheck on every row. Whether it matters is a
question for `EXPLAIN` against production-shaped data, not for a guess — but decide it deliberately.

Also worth confirming while in there: `settled` in `due_captures` filters on the three decline
outcomes, which become the majority of rows on a long-refusing host, and nothing indexes them. And
`ImageCapture` carries only its unique constraint, which may be all it needs.

For `feed_captures`, the sweep asks for head versions with text and no capture at the current parser
version. Index for that query, not for the shape of `page_captures`.

## Hybrid properties

After this change, reading an article is version → extraction → capture → dictionary. Add bridges so
call sites do not walk it by hand. The ones that look like they pay for themselves:

- `ItemVersion.feed_capture`, alongside the existing `latest_capture`
- `ItemVersion.feed_extraction` and `page_extraction` — the latest of each source
- `ItemVersion.reading_extraction` — whichever one `reading_body` picked, so a reader can be told
  where the text came from
- `ItemVersion.has_feed_text` — replaces `octet_length(...) > 0` in the sweep

Rules they have to follow, all of which exist already and are easy to break:

- `lazy="raise"` on every relationship, so a forgotten `joinedload` fails loudly instead of firing a
  query per row
- a correlated scalar goes in a `column_property` with `deferred=True`, like `Item.version_count`,
  or it taxes every `select(Item)`
- a hybrid that only works as SQL raises `NotImplementedError` in its Python half, like
  `Feed.consecutive_failures`
- do not add one with no caller. `vulture` will flag it and the ratchets will bite.

## Verification

- `just check` clean.
- A summary-only version has a feed capture, a feed extraction, and a `reading_body`.
- A content-bearing version round-trips: ingest → capture → `expand` → extraction body unchanged.
- `reading_body` still prefers the page extraction over the feed one when it is fuller, and still
  survives an edit that makes a new version the head.
- Re-run the gate query and report what was actually saved.

## Not in this scope, but decided

Filtering happens in two positions and they are different questions, not two implementations of one.

|              | subject                                         | purpose                        |
| ------------ | ----------------------------------------------- | ------------------------------ |
| pre-capture  | `item_versions` — title, urls                   | do not spend a fetch           |
| post-capture | extractions — both titles, bodies, measurements | do not show the reader rubbish |

Today only the first exists, so a rule misses an article whose page title would have matched —
publishers truncate and prefix feed titles constantly. Adding the second is a `_matches` change plus
a predicate in the river query, not a schema change.

**Neither verdict gets stored, and there is no `blocked` column.** Training rules are hand-made and
edited constantly, and a rule added today has to hide an article ingested last year. A stored
verdict needs every version recomputed on every edit, which is the counter-beside-the-log that came
off `feeds`. The template is `judge()`: extractions store the measurements, because those cannot go
stale, and the question is asked when it is asked.
