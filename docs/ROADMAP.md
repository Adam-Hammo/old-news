# Roadmap

Phase 1 said the next thing would get picked from the corpus instead of guessed at. This is the
pick, plus roughly what comes after.

Deliberately vague on how. Each one gets investigated and scoped when it starts — scoping it now
just builds debt and a document nobody trusts. What's here is the order, why that order, and the
calls already made, so they don't get made twice.

## The bit that actually matters

Everything above the data layer is going to get torn up and redone at some point. The data layer's
job is to make that cheap. Four rules cover most of it:

- **Keep every byte the network handed over.** Feed XML, article pages, images. The rest can be
  rebuilt from those, so the rest doesn't need protecting.
- **Derived stuff gets its own table**, tied to the version it came from, stamped with the code
  version that made it. Never bolted onto the thing it came from.
- **Nothing gets destroyed.** No updates on the append-only tables. Expiry hides, it doesn't delete.
- **Hand-made data is the only data that can't be rebuilt** — thumbs, labels, read state, per-feed
  overrides. Treat it accordingly.

And one about the code rather than the data:

> **Simple code is good code, and good code is elegant code.**

Mostly that means putting a thing where it already belongs instead of building somewhere new for it.
Politeness is the worked example, and it's now been done that way. In `fetch/` it needs a registry
of hosts, last-request timestamps, semaphores and an eviction policy for a dict that grows forever —
and `fetch/` has quietly become a scheduler. As a job option it's `lock=f"host:{host}"`, Postgres
does the serialising, and nothing new got written at all. Same reasoning killed the transition
classifier earlier: it turned out to be a query.

Where it did go wrong: politeness and robots.txt got built as two separate packages a day apart,
even though the note below said outright that crawl-delay was "the same mechanism again". Nobody was
looking across the two. The package tree in `docs/ARCHITECTURE.md` is now checked against the
filesystem by a test, so a new top-level folder fails in the diff that adds it.

The tell is when a module starts holding state about things it isn't about.

Rule two is what makes the pivots cheap. Extraction, embeddings, scores and relatedness each in
their own table means changing tack is a `DROP TABLE` and a rebuild, not surgery on the core. It
also keeps the big tables alone, which matters more as they grow — adding a column to `documents` at
30 GB is a different animal from adding one today.

## What the corpus said

A few days in, 48 feeds, a couple of thousand items.

**78% of what's stored is a teaser.** The feed XML is saved. The article isn't — that only exists on
the publisher's site. Most of the archive has rows for articles it doesn't hold, which is why
extraction is next.

**The version churn is real.** 18% of items get edited. Most of it is live blogs, and the rest is
genuine.

**Same story republished is just a URL match.** Almost nothing gets past it. Relating six outlets
covering one event is a different problem — no shared URL, no shared title — and it's never been
measured, because measuring it needs vectors.

**Publishers do quietly cut things.** Rare, but it happens, and the archive already caught one. See
below.

**Volume's a non-issue for years**, even after extraction. Images could change that.

## Order: what rots

One question sets the order. **Does waiting lose anything?**

Two things rot. Articles and images go offline, get walled off, get quietly rewritten. Training
signal is worse — a thumbs-down with nowhere to click it doesn't exist anywhere, and nobody else
keeps a copy of those opinions.

Everything else waits for free. Search, clustering, folders, expiry, Kindle, backfill. Embeddings
especially: same cost whenever they happen, and they get redone on every model change anyway.

None of this is about speed. Going slow makes the rotting stuff matter more, not less, and costs
nothing at all on the rest. So no rush, and no excuse for cutting corners on groundwork.

Handy side effect — a score is just a function of weights and article, so thumbs can be collected
long before anything scores them, then the whole archive scored retroactively. The reading UI should
be hoovering up opinions from day one, even with nothing to do with them yet.

## Versioning: mostly right already

The append-only chain stays exactly as it is. Two tempting changes, both rejected:

**Storing diffs instead of full content.** Every version beyond the first, across the whole corpus,
comes to under 4 MB. That's the whole prize. Against it: a diff can't be indexed or embedded without
reconstructing it first, and one broken link in a chain takes out everything after it. Right now
every version stands alone and stays readable with no code at all. A diff is a _view_ — compute it
from two versions when something wants to show what changed.

**Letting purely additive changes overwrite instead of versioning.** Only 45% of transitions are
strictly additive, and live blogs — the thing it was aimed at — mostly rewrite in place at the same
length, so it wouldn't even fix them. It also means making a destructive call based on a guess, and
turning a one-line testable invariant into one with a carve-out.

### What the versions are actually for

404 Media published a subscriber article in full to the feed by mistake: 6011 characters. Five hours
later the same item came back at 1577 — same title, and the new text a literal prefix of the old,
cut off mid-article. The archive has the full one.

That's the entire argument for append-only versions in a single row, and it's the shape worth
watching for. Nothing needs building to catch it, though: the versions are already stored, so "which
articles got cut" is a query someone writes whenever they feel like it. It lands on the corpus stats
screen next to everything else.

### Which version gets read

**Latest, by default.** That's structurally true and needs no guessing. It isn't always the fullest
— the 404 Media case proves that — but auto-picking the fullest means a bad guess quietly serves a
stub instead of an article, and a publisher replacing a wrong article with a shorter correct one
would trip it every time. Surface that an earlier version was bigger, let a human decide, and let a
rule fall out of the corpus later if one wants to.

Search and relatedness only ever look at the reading version. For relatedness that's not a
preference: 34 near-identical vectors from one live blog would crowd out genuine matches everywhere
near that topic.

Searching the _history_ is a different question — "find what got deleted" rather than "find the
article" — so it's a second mode, added whenever, cheap because every version is kept.

### Live blogs

This project is article-driven, so they get filtered at ingest eventually. Carefully, and later.
Guardian marks them in the URL, ABC marks them in the title, and the next publisher will do
something else — so "live" is better treated as something observed from churn than a pattern to
match.

## Next: get the actual articles

Fetch the page behind the teaser, keep it, pull something readable out of it.

**Keep the raw page, not just what came out of it.** Extractors improve and the first one will be
wrong. Page still there means a rerun. Page gone means gone. Same argument as keeping the feed XML,
and the only irreversible call in this phase.

**Images too.** Part of the article, they rot faster than text does, and a Kindle page without them
is grim. How many — lead only, or everything in the body — gets decided once the extractor can say
which images are actually the article's. That turns out to be the hard part, not the fetching.

Expect whack-a-mole. Per-site fixes are forever, so they need a home in the database, not in config.
Plus a pile of real pages checked in, so fixing one site can't silently break three others.

Two things to grab while in there, because getting them later means re-running the lot: **the links
out of each article** — free citation graph — and whatever the page claims about itself.

**Fetch the page once per version. Extract only the reading version.** Fetching is capture — the
page as it stood at that moment rots and can't be got back, so a new version means a new fetch.
Extraction is derivation: disposable, re-runnable from the stored page any time, so only the reading
version needs current output. That way a wrong reading-version guess costs a rerun rather than the
article.

It's about 55% more fetches than one-per-article, and live blogs are a sixth of that — which is a
concrete reason to filter them at ingest beyond just tidiness.

Extraction output is versioned on two axes: which item version it came from, and which extractor
made it. Re-extracting inserts rather than overwrites. Unlike item versions, extractions are derived
and disposable, so old extractor output can be binned freely.

Two structural notes so this doesn't get built wrong. Extraction output can't live on
`item_versions` — that table is append-only and describes what a feed document said, and adding
derived fields means updating it. And extraction is **its own task, triggered by a new version, not
a step inside the poll**. A poll stays one fast job, a failing extractor doesn't fail a poll,
retries are independent, and re-extracting an old article runs down exactly the same path as
extracting a new one.

## Then: Kindle, via Calibre

An output feed of full text and images. A Calibre recipe eats it and sends it to the Kindle.

Small, and it does three jobs. It's the offline answer, so the web UI never has to become a proper
app with sync. It's somewhere to read before the UI exists. And it's an honest test of extraction —
bad extraction is obvious on a Kindle page in a way it never is in a query.

## Then: somewhere to read it

Own web UI. Phone first, plain server-rendered pages.

**No login.** Tailnet-only, so there's nothing to log into and a pile of work vanishes.

GReader stays dead. It can't express training, scoring, the river, Voices or labels — five features
with no vocabulary in the protocol, and most of the point of the app.

What's in it:

- **Keyword search.** Cheaper than expected: `pg_search` is already in the image, unused. Most
  searches are keyword searches.
- **The river**, Currents-style. Things age out of view, no unread counts, a line marking where new
  stuff starts. Out of _view_ — nothing leaves the database, and anything labelled never ages out at
  all, or the river eats the thing that was deliberately kept.
- **Labels that do things.** Saved, send-to-kindle, download. One labelling idea where some labels
  carry behaviour, instead of a new boolean column every time.
- Folders or Currents, whichever those turn out to be. Those are about feeds. Labels are about
  articles.
- **Thumbs, collected, unused.**

Authors need sorting out around here. Two features want them — following a person instead of a feed,
and training on an author — and right now they're 673 messy strings with a third of them blank.

## Then: training

Thumbs up and down on tags, authors, title phrases, feeds. Global, with per-feed overrides.
Filtering first — hide the rubbish — and leave ranking until the rules are dense enough to sort by.

**It's not a sum.** The obvious guess is that each thumb adds ±1 and an article's score is the
total. NewsBlur doesn't do that. Each dimension settles on one value, then the strongest positive
wins outright — except a "never show me this" tier that beats everything, and the feed's own score,
which only counts when nothing else has an opinion. Green beats red.

Better than a sum, for two reasons. A sum makes the score depend on how much training has happened
rather than what got trained, so the cutoff drifts as rules pile up. And max/min stays explainable —
there's always exactly one rule to point at. A sum gives you "nine rules came out to -2", which
tells you nothing and can't be debugged.

It's coarse, and there's nothing to rank on. Fine for now, and cheap to change later: the weights
are the part that can't be lost, the combining rule is just code. So store proper integer weights
even though three values is all the current rule needs.

Stays deterministic and explainable either way — same weights and same article, same score, and the
UI can name the rules that did it. NewsBlur has since bolted an LLM onto this. That's the part to
skip.

## Two kinds of per-feed knowledge

Both hang off a feed, so they'll want merging. Don't.

**Observed properties** — ships full text, churns 14x, guids rotate, titles start with "Live:". All
measured from data already held. Nothing to train, nothing to maintain, and self-correcting when a
publisher changes behaviour.

**Hand-set overrides** — use this selector, never version this feed, poll it hourly. Genuinely
hand-made and unrecoverable, so rule 4 applies.

Most of what looks like per-feed training is the first kind, and the residue only grows when
something is actually broken. Reader training is a third thing again — that one's taste, which
nothing can derive. Different lifecycles, so different tables and different screens.

## Then: search, properly

Really good search and really good relatedness are the same job. Three layers, cheapest first:

1. **Links** — who cites whom. Falls out of extraction. No model, exact.
2. **Keyword similarity** — more-like-this over the search index. Still no model.
3. **Semantic** — embeddings and nearest-neighbour. Catches six outlets on one event where nothing
   matches on words.

Last because it loses nothing by being last, not because it's hard.

Relations get stored as their own rows, joinable and explainable, which is the elegant version. But
they split by how they behave. **Facts** — this article links to that one, these two share a
canonical URL — are exact, immutable and cheap, so they get materialised. **Opinions** — these two
are about the same thing — come from a model, change when the model changes, and every new article
wants relating backwards against everything already held, so a stored version is never finished.
Same table, a column recording which produced the row, and the half that would rot silently gets
rebuilt rather than trusted.

One call worth making now because it's free now and irritating later: **embeddings get their own
table, recording which model made them.** A plain vector column forces picking dimensions before
picking a model. Worse, swapping models silently rescores the whole archive with no error, and
quietly voids every trained weight.

## Someday: reaching backwards

Wayback, sitemaps, publisher archives. Filling in from before the subscription existed. Dead last —
those archives aren't going anywhere. The only thing to not screw up early is recording where a
document came from, because one pulled out of Wayback isn't a feed poll.

## Done: politeness and robots.txt

Turned out to be exactly what the guess above said, which is the first time that's happened.

`lock=f"host:{host}"` on the deferred job. Four feeds from one publisher stop being four
simultaneous connections and become four in a row, and `fetch/` never learned anything. A batch is
also spread out with `schedule_in`, because the lock alone lets them run back-to-back as fast as
each poll finishes. That gap collapses if a host is slow — the requests stay one at a time, so the
host's own slowness does the spacing instead.

Worth knowing: a failed job doesn't hold its lock, so one broken feed can't stall the rest of its
publisher. That was the thing most likely to make this a bad idea, and it isn't one.

robots.txt is a table of host rules, one row per host, refreshed by a task and overwritten in place.
A cache, so none of the append-only rules apply to it. `crawl-delay` comes back out as a longer
`schedule_in`, and may only slow things down, never speed them up — same as a feed's `<ttl>`. A host
that can't be reached is carried on past, and asked again sooner.

The standard library turned out to be enough. Python 3.14's `robotparser` does wildcards and
longest-match precedence properly, which older ones didn't, so no dependency. One trap: parsing
alone leaves it refusing everything until it's been stamped as modified.

`Disallow` is obeyed for polls too, with one carve-out. A blanket `Disallow: /` gets ignored,
because RSS is published for readers — a site that ships a feed and bans every bot is stating a
crawler policy, not withdrawing the feed it published. A rule that names the feed is a different
thing and gets obeyed. Such a feed is backed off rather than suspended and isn't counted as a
failure, so deleting the rule brings it back with nobody doing anything.

Hosts got their own table on the way through. `feeds.host` and `robots_policies.host` used to be
loose strings that matched only because the same function produced both — change how a host is
derived and every stored row silently stops being found. Now they're foreign keys into `hosts`,
whose key is the host itself rather than a uuid, because a host is its own identity and a join to
read one buys nothing.

Polling had been quietly half-broken the whole time, which only turned up because the queue gauges
were there to look at. A `queueing_lock` collision — a feed still waiting from the last sweep —
comes back from procrastinate as an exception, so the scheduler died on the first one and every feed
after it in that batch went unpolled. Thousands of failed scheduler jobs, no alarm, feeds just
getting visited less than they should. The per-host lock made it more likely, since jobs now sit in
the queue on purpose.

One thing it doesn't do: the robots table has no cleanup. Unsubscribe everything from a host and its
row just sits there, a few hundred bytes, never refreshed again.

The `Fetcher` is now built once per process instead of once per job, so a poll no longer pays for a
fresh connection.

## Things that'll bite anyway

**Reprocessing mustn't starve the live path.** Re-extracting the archive or re-embedding after a
model change runs on the same worker as the polls keeping the archive current. There are queues
already, so this is nearly free to get right and irritating to retrofit.

**The hand-made data wants backing up separately.** Thumbs, labels, read state and overrides are the
only things that can't be rebuilt, and right now they're buried inside the same dump as the tens of
gigabytes that can be. A few megabytes exported on its own is silly cheap insurance.

**Corpus stats somewhere visible.** This project decides things by looking at the data, and right
now that means hand-writing SQL. Feed health goes on the same screen — Logfire already handles
alerting, so this is for looking, not for noticing. Most of the questions PHASE-1 wanted answered
still want weeks of corpus rather than days, so this is how they get answered.

**Extraction needs a quality signal, not just success or failure.** The failure that matters isn't a
404, it's cheerfully extracting a cookie banner and marking it done.

**Feeds that move don't get updated.** A permanent redirect gets followed forever instead of
recorded, which also lets a retired feed look healthy. Small. Worth fixing whenever.

## Still undecided

- What to call the extraction output table. Body, byline, images and links in it, so not "text".
- Lead image only, or every image in the body. Roughly 10x the storage between them, and probably
  unanswerable until the extractor can scope them.
- Whether feeds that already ship full text get their pages fetched anyway — more traffic and
  storage, but it's where the images and the citation links live.
- What "read" means in a river with no unread counts.
- What the river sorts on. Publisher dates are already dodgy, and backfill would flood the top with
  2019 articles.
- Whether folders and Currents are one idea or two.
- Whether a filtered-out article is hidden, or collapsed to a line that expands.
- Whether the free URL-match dedup is worth doing before relatedness exists, or just shuffles rows
  around for nothing.
