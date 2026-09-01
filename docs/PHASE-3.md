# Phase 3 — somewhere to read it

A web UI over the archive. River, article, sections, and nothing else.

## Why this jumped the queue

The NewsBlur subscription expired, so there is nowhere to read any of this.

The roadmap put Kindle first and gave it three jobs: the offline answer, somewhere to read before
the UI existed, and an honest test of extraction. The second is now moot. The first is handled
outside this repo — Calibre already works, independently, and stays that way. The third moves onto
the article screen, which is the reason that screen gets built second and stared at before anything
else is drawn.

## What is in it

A river and an article. That is the whole of it, and there is no nav, because there is nowhere else
to go.

Archive was in the nav for a while and has been taken out again. It was designed far enough to know
it works — three ruled columns grouped by section, one column on a phone, the same shell as the
river — and it earns its place on the day one of two things is true: the river starts ageing things
out of view, or search exists. Until then it is a second door into a list nothing has fallen off
yet.

Not in it, deliberately: thumbs, search, labels, filtering, offline reading, and the marker showing
where reading stopped. Each is named again at the bottom with what it is waiting for.

## What got decided

**Categories stay the string they already are.** `subscriptions.category` exists, is indexed, and is
already populated: `subscriptions/opml.py` walks nested outlines and files each feed under its
container's title, so an imported OPML arrives with its folders intact and round-trips back out. One
category per feed, empty meaning unfiled.

Promoting it to `sections` and `section_feeds` was drafted and dropped. Many-to-many looked like the
answer until the case that motivated it was examined: 404 Media runs a science column inside a
mostly-technology feed, and putting that feed in both Technology and Science does not surface the
column, it pollutes both filters with the other's items. The problem is that a section wants to be
about items and a feed subscription is about sources, and no amount of many-to-many bridges that.

Expressing it properly means item-level membership rules, and the vocabulary for those is already
built: `training_rules` carries a dimension, a case-insensitive substring pattern and an optional
feed scope, which is exactly "404 Media, title contains The Abstract". That is the shape to reach
for when this is worth solving. It is not worth solving before anything has rendered, and the same
table should not serve both &mdash; grouping and hiding have different lifecycles and different
screens, which is the roadmap's own test.

So a category is coarse on purpose, and it is more useful as a mode than a topic: firehose against
long-form is a distinction that changes how something gets read, and it is one a feed can honestly
carry whole.

**Read is two things wearing one word.** Opened is a fact about an item, and `items.read` and
`items.read_at` are already there to hold it, so nothing new is needed for it. Where reading stopped
is a position in a river, which is a different shape entirely and depends on a high-water mark that
does not exist yet, so it waits. Neither produces an unread count; the roadmap already ruled those
out and nothing here reopens it.

**The river sorts on first seen by us, not the publisher's date.** It is the only timestamp under
this project's control, it is monotonic, and it is the one that stops backfill flooding the top with
2019 the day someone reaches backwards. The publisher's date is displayed and never sorted on.

**No thumbs.** The roadmap wants opinions hoovered up from day one, and that is overruled: training
starts fresh later rather than importing anything out of NewsBlur. What the design does owe it is
room — the item row has to be able to carry an affordance and to collapse to a single line, or
filtering later is a redesign rather than a diff.

**No time separators in the river.** They were structure standing in for a read position, and once
the read position is gone they are decoration.

## The stack

**SvelteKit, Svelte 5 runes, against a Litestar JSON API.** Python stays the backend and stops
there.

The roadmap's call was plain server-rendered pages. That is superseded. Jinja is untyped and
un-refactorable and logic leaks into it, but the honest reason is different: this is a chance to
learn a frontend framework properly, and the project is personal enough to spend that. Svelte earns
it over React and Vue because a component is HTML with a script and a scoped stylesheet, which suits
a design carried by typography and plain CSS rather than by a component library.

Rejected on the way past: a hypermedia-only stack, which is the lower-maintenance answer and the
right one if longevity were the goal; and a sync engine owning the data path, which fights "services
hold the logic" directly.

- **The contract is generated, not written.** Litestar already emits OpenAPI at `/schema`.
  `openapi-typescript` turns it into the client's types, so the two languages cannot drift without
  the build saying so.
- **`web/` is a sibling of `src/`, not a package inside it.** The rules in CLAUDE.md govern
  `src/old_news/` and the architecture test reads its tree from `docs/ARCHITECTURE.md`; a second
  language needs its own conventions rather than a carve-out in those.
- **Serving is one more unit.** `adapter-node` on a second port, and `tailscale serve --set-path`
  routing `/api` to Litestar and everything else to node. No reverse proxy is introduced.
- **Plain CSS.** Custom properties in one stylesheet, self-hosted faces, scoped styles per
  component. No utility framework: this design is set by type and rules, which is the thing utility
  classes are worst at.
- **Endpoints stay query-shaped.** Section, cursor, limit — not verbs. That is the single constraint
  honoured now so a local-first store can sit under the read path later without the API being
  rewritten. It costs nothing today.

## Two panes

Desktop is a list beside an article, and the list column is the phone's browsing surface at 430px
rather than a second design: the same section strip and the same rows, no breakpoint between them.
Every view is then a different query into that column, which is why Archive costs almost nothing to
add back later.

The masthead stays above both panes rather than moving into the list. Pushing the whole phone screen
into the left column would put a masthead sized for 390px next to a 42px headline, so the app name
ends up smaller than one story's title.

**No hamburger.** Navigation is two destinations; hiding two words behind a tap buys nothing.
Article actions are the thing that wants hiding, and they go in a sheet behind an overflow control
&mdash; which is also where saved, send-to-Kindle, thumbs and label land later without the article
screen being redrawn. Moving to the next item stays on the bar, because it is the primary action and
should never cost two taps.

**Neither component knows about the viewport.** There is a river and there is an article, both
fluid, both rendering the same at 390px and at 430px and at 900px. What changes with width is the
shell around them: one pane on a phone, two on a wide screen. That keeps the media query in exactly
one file and means the river is never "in mobile mode" &mdash; it is just narrow, which is a
property of the box it was given rather than a state it holds.

The consequence worth stating now, because it is unpleasant to retrofit: **the river's data is
loaded by the layout, not by the river's route.** On a wide screen the article route has to render
with the river still beside it, so the list cannot belong to the page that the article replaces.

**A category is a set of feeds, and the UI must not pretend otherwise.** Every river row carried a
section name above its headline until it was noticed that a feed in two sections has no correct one
to show. The row was claiming a per-item topic that nothing in the model holds, so it is gone and
the outlet in the byline does that work.

Where a feed genuinely spans several sections, the fix is the subscription rather than the schema:
big publishers ship a feed per section, and `subscriptions/discover.py` is how you find them. It
only fails for a publisher that covers several topics behind one feed, and multi-membership already
handles that — the feed's items turn up under either section, which is right.

Real per-item topics are a different feature. `item_versions.tags` already holds the publisher's own
category terms from ingest, and that is where a kicker would come from if one comes back, once
somebody has measured how many items carry one. It is about articles rather than feeds, which by the
roadmap's own division makes it a label rather than a section.

**There is no settings screen.** Managing feeds already has two answers in the repo. `sqladmin` is
mounted and carries `FeedAdmin` and `SubscriptionAdmin`, so a category or an `active` flag is a form
that exists; `FeedPollAdmin` lists every poll with its outcome, status and error, which is the feed
health screen. OPML is `old-news opml import` and `old-news opml export`. Logfire does the noticing.

A prettier version of all that was drawn and thrown away. It is the failure the roadmap keeps
naming: building somewhere new for a thing that already has a home. What would justify one later is
something none of those can do &mdash; filing a feed from a phone, or subscribing from a pasted URL
through `subscriptions/discover.py`, which is the one capability with no interface at all.

**There is one now, and it is only that.** `/settings` follows a pasted address, files a feed under
a section and drops it, because those are the three that fail the test above. Everything else about
a feed is still sqladmin's: nothing here reads a poll outcome, an error or a schedule. Dropping is
the subscription going inactive, so the archive survives what a person changes their mind about.

**No Next on the article.** With no Prev beside it, one mis-tap loses the article with no way back
to it, which is a poor trade for saving a tap. Back to the river is the whole of the article's
navigation, and gestures can revisit it later. That makes **restoring the river's scroll position a
requirement rather than a nicety**, since it is now the only way back to where you were.

**Lead images in the river: not yet, and not for the reason first given.** The density objection
does not survive contact with a mock-up &mdash; a 72px thumbnail sits inside a row that is already
about 96px, so the list does not grow at all. What does bite is the rendition. `image_captures`
holds one `body` and one `spec`, so there is exactly one rendition per capture and bumping the spec
re-encodes the archive to it. A river thumbnail therefore means either shipping the full reading
image and letting CSS shrink it, which is careless over cellular at four hundred rows, or a second
rendition, which by rule 2 wants its own table rather than another column on `image_captures`.

Coverage is also unmeasured, and this project decides things by looking:

```sql
select count(*)                                                as lead_slots,
       count(*) filter (where ei.image_capture_id is not null) as fetched,
       count(*) filter (where ic.body <> ''
                          and ic.status between 200 and 299
                          and ic.content_type like 'image/%')  as usable
from extraction_images ei
left join image_captures ic on ic.id = ei.image_capture_id
where ei.role = 'lead';
```

So the river ships without them, and they get added on the day the rendition question is being
answered anyway. The form is settled either way: a fixed-size thumbnail on the right of the row when
there is one, text running full width when there is not.

## The data that cannot be rebuilt

Rule 4 applies to everything this phase writes, which is the reason the schema lands before any
markup:

- **Categories**, as the string on each subscription. Hand-made and unrecoverable, and already
  carried by a column that exists.
- **Opened items.** Already has its columns on `items`; what is missing is anything that writes
  them.

Both are small enough that the roadmap's note about backing hand-made data up separately stops being
theoretical the moment they exist.

Where the logic lives is a new top-level package, and that is a decision to make out loud rather
than in passing. It goes in the tree in `docs/ARCHITECTURE.md` in the same diff that creates it —
adding it earlier fails `test_the_documented_tree_has_no_ghosts`, which is the test doing its job.

## Networking

`tailscale serve` already terminates TLS on the MagicDNS name, so there is a real certificate on a
`*.ts.net` address with no DNS records and no renewal. That is what makes the rest cheap: no login,
because there is nothing exposed to log into; add-to-homescreen behaves; and a service worker is
allowed to run, because the origin is secure.

`funnel` stays off. Tailnet-only is what makes no-auth safe, and the two decisions are the same
decision.

**A service worker, for one job.** Not offline reading — a page instead of Safari's error when the
app cannot be reached. It can tell the two failures apart honestly: a 5xx means the host answered,
so the tailnet is up and the app is not; a thrown fetch means the tailnet is down. Nothing else is
cached and no reading works offline.

Rejected: bridging to the Tailscale app from that page. It publishes no URL scheme and no universal
links — `tailscale.com` and `login.tailscale.com` both 404 on
`.well-known/apple-app-site-association`, and the request for a scheme is open and untriaged. The
only public hook is a hand-built Shortcut, which is friction moved rather than removed.

**The river runs full width until the first click.** That was the third of three bad options and it
is the least bad: auto-opening the newest item is presumptuous and marks it read, and a blank pane
wastes half the screen on arrival. The page moves once per session and then stops. What softens it
is that the rows do not move much — a row's text is held to a measure either way, so the full-width
river is the column it is about to become, with more paper beside it.

**Decks show at every width.** They are what the row is for. Dropping them on a phone would have
been the component knowing how wide it is, which is the one thing this design says it must not do.

**One paragraph had to lose.** "Moving to the next item stays on the bar" and "No Next on the
article" cannot both hold. No Next won: it is the later and more specific of the two, and it is
argued rather than asserted — with no Prev beside it, one mis-tap loses the article. The bar is Back
and the overflow control, and nothing else.

## Still undecided

- **Teaser images in the river.** Left out, and the reasoning is under Two panes.
- **What happens when sections outgrow the strip.** It scrolls, with a pinned control opening the
  full list, so nothing is unreachable. Past six or seven a 430px strip stops being a good primary
  filter, and a wide screen would want the section rail back as a third pane.
- **Authors.** The article screen displays them and two later features want them, and they are still
  673 messy strings with a third of them blank. Displayed raw for now, normalised when something
  needs it to be.
