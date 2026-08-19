# Phase 2 — the actual articles

Fetch the page behind the teaser, keep it, and pull something readable out of it.

78% of what the archive held was a teaser. The feed XML was kept; the article only existed on the
publisher's site. Articles and images are the two things that rot while everything else waits for
free, which is the whole reason this went first.

## What the corpus decided

Every number below came out of the live archive before any of this was written — 43 feeds, 2,738
items, 4.7 days — because the alternative was guessing.

**Full-text feeds already carry their links and images.** 97.6% of full-text items have real
`<a href>` links, averaging 31 an article, and 82.2% have `<img>`, at 3.8 images each. So the page
is not where a blog's citations or pictures come from. Partial feeds average 2.3 links, which is
"continue reading" boilerplate, and teasers have essentially nothing. The page is worth fetching
anyway, but only because fetching everything is cheaper than deciding — not because there is much
there.

**Churn is two things wearing one costume.** 65% of items have a single version. Of the rest, live
blogs carry a `/live/` or `live:` marker about half the time; the other half are real articles
rewritten as a story develops, at 38 and 32 versions. One is unwanted content, the other is wanted
content arriving badly, and they need different answers. Live blogs replace their head every 25
minutes at the median against 107 for everything else, so timing separates what a pattern cannot.

**A dictionary halves the largest thing in the database.** Ten consecutive Guardian feed documents
average 392 KB raw: 88 KB each at the old default, 81 KB at level 12, and 44 KB with a per-feed
dictionary. Article pages gain less, 47 KB to 39 KB.

**Images are the only line that neither compresses nor shrinks.** Text and derived rows come to
about 11 GB a year at the target corpus. One image an article is another 14 GB — more than half the
archive on its own. Every image at original size is nearer 47 GB.

## The three sweeps

Extraction is not a step inside a poll. It is three sweeps on their own queue, each asking what the
archive is missing:

```text
no page yet          →  fetch it, keep the bytes          page_captures
page but no text     →  read it, keep what it said        extractions
text but no picture  →  fetch the lead image             image_captures
```

A failing extractor cannot fail a poll, retries are independent, and re-capturing a five-year-old
article runs down exactly the same path as capturing one that arrived a minute ago. The queue is
separate so that re-running the archive later cannot starve the polls keeping it current — the
roadmap called that nearly free now and irritating to retrofit, and it turned out to be one string.

### Which pages get fetched

`extract/due.py` holds the whole rule in one query, so it reads in one go and is tested case by case
rather than by inference.

**The first version of an item is captured immediately.** That is what guarantees every article has
something, and it closes a hole a settle-only rule would leave: 404 Media replaced a full article
with a truncated one after five hours, but a publisher who pulls a mistake in ten minutes would
leave a settle-only rule holding nothing at all. First and final is the pair that matters, and only
the first is certain to be reachable.

**Later versions wait an hour.** A rolling story getting eight versions in three hours is captured
three times rather than eight. The versions superseded inside the window are skipped and their pages
are genuinely lost — what survives for them is the feed's own text, since `item_versions` is
untouched. Every version the publisher announced is still there; only versions that stood still long
enough earn a request.

The window is a freshness dial, not a storage one. Over 2,229 articles: 3,940 captures naive, 2,866
at an hour, 2,793 at two, 2,712 at six, and 2,165 if later versions were never re-captured. Six
hours buys 5% over one, because real edits are either fast — live blogs — or slow enough to clear
any window worth setting. So an hour, and nothing here is worth tuning.

**Two brakes on top.** An item stops being eligible at five versions, counted on versions rather
than captures so the bound holds however the window is set. And a blocking training rule skips an
item from first sight. Together: 2,815 captures where naive is 3,940, which removes 65% of the
excess over one each, and what remains is articles genuinely edited twice.

Nothing is destroyed to achieve that. All 723 live-blog versions cost 3.3 MB and stay — they are the
evidence the churn brake reads, and a false-positive rule costs a re-runnable capture and nothing
else.

### What a capture is

`page_captures` is append-only and deliberately not unique on the version. A 403 on Tuesday and the
page on Friday are both facts about the archive; "the capture" is the latest successful row. That
makes "which articles could not be captured" a query, and it bounds a retry without ever updating a
row.

`host_id` is a foreign key rather than a host derived again from the URL at read time. That is
exactly how `feeds.host` used to drift, and one function has to own how a host is worked out.

Two guards earn their place. **Content type is checked before the body is read**, because an
aggregator points at PDFs and video and the body cap is 16 MB. And **`robots.allows` is the gate** —
the strict one, with no blanket-ban carve-out, because a feed is published for readers and an
article page is not. It had been sitting in `robots/service.py` with that exact docstring and no
caller since the phase before.

**Article hosts joined the robots driver**, which is the bug this phase found rather than made.
BBC's feed is on `feeds.bbci.co.uk` and its 183 articles are on `bbc.co.uk`, and a host with no
stored rules reads as allowing everything. Fetching those articles would have crawled a host whose
robots.txt was never read and been told yes because nobody asked.

### What an extraction is

Derived, disposable, and versioned on two axes: which item version the text came from and which
extractor made it. Re-running the same extractor rewrites its own row; bumping the extractor makes
the whole archive due again without anything deleting anything.

Output is markdown — the smallest of the options, and both the Kindle HTML and the search text are
views of it rather than second copies.

**The quality signal is the point of the table as much as the body is.** The failure that matters is
not a 404, it is cheerfully extracting a cookie banner and marking it done. Measured: Guardian
articles come out at 3,500–7,400 characters over 15–29 paragraphs, a consent wall at 170 over one.
Link density is recorded and is _not_ what catches it — trafilatura strips a consent wall's links
and the number reads 0.0, so length and paragraph count do that job. A row that fails the signal is
still stored, because the judgement is the part most likely to be wrong.

**Which body a reader sees is a view, not a column.** For a full-text feed the feed's own content
usually wins, for a teaser the extraction does, and 404 Media proves the feed is sometimes the
fuller of the two. One function decides it, so the rule can change without a migration and without a
second copy of the text.

### Images, held to one

The lead image is fetched unasked, because it is the one picture that stops a card or a Kindle page
having a hole in it. Body images are the same task with a different argument, waiting for a reader,
a Kindle build or a label to ask — which is the label mechanism the roadmap already names rather
than a sibling of it.

Keyed on the URL digest and the bytes together: on the digest because an image URL can exceed what
btree will take and a CDN's query string is part of its identity, and on the bytes as well because a
re-crop lands on the same path and keying on the URL alone would conflate two images and quietly
keep the older one. A publisher's series header across forty posts is one row.

Bytes are kept as received and never re-encoded. The rendition a phone wants is derived from these
later; one that replaced them could not be undone.

The honest cost: body images behind articles nobody opens, and behind articles opened a year later,
will be gone. It is measurable whenever it matters — run the capture over a month-old sample of
stored URLs and count what 404s — and nothing about recording the URLs now has to change for that to
happen.

## What moved into the ORM

The sweeps were each re-deriving the same four things, so they moved onto the models as hybrids —
`ItemVersion.is_head`, `ItemVersion.feed_body`, `PageCapture.succeeded`, `Feed.subscribed` and
`Item.subscribed` — plus `Item.version_count` as a deferred `column_property`. The capture sweep's
`WHERE` now reads as the phase's rules rather than as an anti-join and two subqueries, and
`ARCHITECTURE.md` records which predicate lives where.

Measured on the live archive afterwards, so this was not a guess about the planner: 6 ms, with
`version_count` evaluated 28 times rather than per item because the `LIMIT` short-circuits, and
`subscribed` memoised at 24 cache hits out of 28. `EXPLAIN` also found the one real gap — the "which
versions already have a page" check was a sequential scan on what will be the fastest-growing table
here, so it got a partial index on `item_version_id` covering only successful rows.

## Enums in Python, strings in Postgres

A closed set of values — a rule's dimension, its provenance, an image's role — is a `StrEnum`, and
the column is a `VARCHAR` whose check constraint is spelled from the enum's members, so the two
cannot drift.

`sa.Enum` looked like the obvious way to say that and is a trap at both settings. A native Postgres
type cannot gain a value in the same transaction as the migration needing it. And with
`native_enum=False`, alembic renders the member _names_ into the check constraint — `'URL_PATTERN'`
— where the application writes the _values_ — `'url_pattern'` — so every insert fails against a
constraint that looks right in the model. That one only showed up because a migration silently
refused to apply.

## The first training rule

The live-blog marker is not a regex in the capture query. It is a row in `training_rules`, which is
the table thumbs and scoring land in later.

Only the blocking tier exists — "never show me this", which beats everything. Matching is
case-insensitive substring via `position`, not LIKE: the pattern is a column, so there is nothing to
escape client-side, and `position` has no wildcards to begin with. Every rule the corpus justifies
is a substring anyway.

The dimension and source check constraints list what is _implemented_ rather than what is planned,
so a rule that could never fire cannot be stored. Adding a dimension is a branch and a migration
together.

Two rules are seeded, scoped to the publishers whose conventions they are rather than globally,
because `/live/` in a path means a live blog at the Guardian and could mean anything elsewhere.
`/live/` matches 47 items, 38 of them churning hard. `live:` in a title is ABC's convention, and
every match inspected was a live blog. Deliberately not seeded: `-live-`, which also matches
`gpus-live-longer` and `sydney-live-music`.

Rules are hand-editable in Admin because they are the first unrebuildable data in the system — the
`source` column is what says which ones that applies to, and it is what the roadmap's
separate-backup note is actually about.

The five-version cap is deliberately _not_ a rule. It is an observed resource bound, not taste;
different lifecycle, different home.

## Compression, done properly

The dictionary work was going to be deferred and was not, because it turned out to pay off on the
biggest line rather than the newest one. `db/bytes.py` is the only module that imports zstd, the
level is config, and `ARCHITECTURE.md` carries the three properties that make it safe: a frame names
its own dictionary, nothing is ever rewritten, and no dictionary is always correct.

One trap worth recording. `dict_id` hashes the dictionary's content, so a feed whose documents have
not changed in character retrains to a byte-identical dictionary and the same id. Keyed globally
that is a unique violation and a failed nightly job for no reason; keyed on the dictionary _and its
scope_ it is a no-op that moves `trained_at`. Another: zstd's trainer refuses fewer than about eight
samples whatever dictionary size it is asked for, so that floor is in code rather than left to
configuration.

## Deferred, with the reasoning kept

**Per-site extraction rules.** The roadmap is right that per-site fixes belong in the database and
wrong to fix their shape before one site has broken. Run the generic extractor across the corpus and
the shape is evidence. When it lands it hangs off `hosts`, not `feeds` — a template is a property of
a site, and BBC proves the two differ.

**Links as rows.** They are captured as JSONB. The relation they want to express is
article-to-article, which needs URL-to-item resolution that arrives with dedup in the search phase;
materialising them now would be millions of rows of unresolved URLs that get re-derived anyway.

**Integer weights on training rules.** The blocking tier is a different kind of statement from a
trained strength, and `training_rules` will always be small, so the column arrives with the thumbs
that set and read it rather than sitting empty.

**Body image bytes.** Recorded as URLs and slots, fetched when asked. See above for what that costs
and how to measure whether it was the wrong call.

**Raw pages are the one line that can be expired**, and nothing else is. Extractions survive; what
would be lost is re-extracting old articles with a better extractor. Last resort, and the reason the
page and its extraction are separate rows in the first place.
