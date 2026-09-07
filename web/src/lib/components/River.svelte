<script lang="ts">
	import { navigating } from '$app/state';
	import * as api from '#lib/api/client.ts';
	import type { Entry, Listing } from '#lib/api/client.ts';
	import { finished } from '#lib/finished.ts';
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';
	import { opened } from '#lib/opened.ts';
	import { stamp } from '#lib/format.ts';
	import { marked } from '#lib/snippet.ts';
	import { whenVisible } from '#lib/visible.ts';

	let {
		page,
		view,
		selected,
		dense = false,
	}: { page: Listing; view: View; selected: string; dense?: boolean } = $props();

	// One discriminator now: in the archive is exactly "there is a query".
	const archived = $derived(links.archived(view));
	const empty = $derived(archived ? 'Nothing matched.' : 'Nothing here yet.');

	// Pages fetched after the first, tagged with what they were fetched behind. Reconciled
	// in a `$derived` rather than cleared in an `$effect`: an effect runs after the render
	// that would already have drawn a refetched first page beside rows it now repeats, and
	// one duplicate key takes the whole screen down.
	let appended = $state.raw<{
		of: View | null;
		behind: string;
		entries: Entry[];
		cursor: string;
	}>({
		of: null,
		behind: '',
		entries: [],
		cursor: '',
	});
	let loading = $state(false);
	let failed = $state(false);

	// Both by identity, which is what the tag is raw for: `$state` hands back a proxy of
	// the view rather than the view. Two views can end their first page on the same row,
	// so the cursor alone does not say these rows belong under the one on screen.
	const beyond = $derived(
		appended.of === view && appended.behind === page.cursor ? appended : null,
	);
	const entries = $derived([...page.entries, ...(beyond?.entries ?? [])]);
	const cursor = $derived(beyond ? beyond.cursor : page.cursor);

	async function more() {
		const of = view;
		const behind = page.cursor;
		const at = cursor;
		if (!at || loading) return;
		loading = true;
		try {
			const next = (await api.listing(fetch, of, at)).listing;
			appended = {
				of,
				behind,
				entries: [...(beyond?.entries ?? []), ...next.entries],
				cursor: next.cursor,
			};
			failed = false;
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	}

	function href(id: string): string {
		return links.item(id, view);
	}

	/** Solid once a book carrying it has gone; dashed while it is only due to. */
	function mark(entry: Entry): '' | 'sent' | 'queued' {
		if (entry.sent) return 'sent';
		return entry.queued && !finished.has(entry.id) ? 'queued' : '';
	}

	// The article's own load has to answer before the pane can swap, so without this a tap
	// on a slow connection looks like a tap that missed.
	const opening = $derived(navigating.to?.params?.id ?? '');
</script>

<ol class:dense>
	{#each entries as entry (entry.id)}
		{@const kindle = mark(entry)}
		<li>
			<a
				href={href(entry.id)}
				class="row"
				class:read={entry.read || opened.has(entry.id)}
				class:selected={entry.id === selected}
				class:opening={entry.id === opening}
			>
				<h2>{entry.title}</h2>
				<p class="by">
					<b>{entry.outlet}</b>
					{#if entry.author}<span class="author">{entry.author}</span>{/if}
					{#if kindle}
						<span
							class="kindle {kindle}"
							title={kindle === 'sent' ? 'On the Kindle' : 'Due on the Kindle'}
							>K</span
						>
					{/if}
				</p>
				{#if dense && entry.published_at}
					<span class="when">{stamp(entry.published_at)}</span>
				{/if}
				<!-- Rendered as text, never as markup: the fragment is a publisher's prose. -->
				{#if entry.snippet}
					<p class="found">
						{#each marked(entry.snippet) as run, index (index)}
							{#if run.hit}<b>{run.text}</b>{:else}{run.text}{/if}
						{/each}
					</p>
				{/if}
			</a>
		</li>
	{/each}
</ol>

{#if entries.length === 0}
	<p class="note label">{empty}</p>
{:else if failed}
	<p class="note label"><button onclick={more}>Could not load more. Try again.</button></p>
{:else if cursor}
	<div use:whenVisible={more} class="note label more">{loading ? 'Loading…' : ''}</div>
{:else if archived}
	<p class="note label end">That is everything held here.</p>
{:else}
	<!-- The end of the river is where the door has to be, or ageing out loses things. -->
	<p class="note label end">
		<a href={links.archive()}>Older stories are in the archive &nbsp;&rarr;</a>
	</p>
{/if}

<style>
	ol {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	/* The left border is transparent on every row so selecting one moves nothing. */
	.row {
		display: block;
		padding: 11px var(--gutter) 13px;
		border-top: 1px solid var(--hair);
		border-left: 3px solid transparent;
	}

	li:first-child .row {
		border-top: none;
	}

	/* The rules run the width of the pane; the words do not. Before the first article is
	   opened the river has the whole window, and a 1440px headline is not a headline. */
	.row > * {
		max-width: var(--measure);
	}

	.row.selected,
	.row.opening {
		background: var(--paper-read);
		border-left-color: var(--rule);
	}

	/* Only while the load is out. It settles into `.selected`, which looks the same
	   without the pulse, so nothing moves when the article arrives. */
	.row.opening {
		animation: waiting 1.1s ease-in-out infinite;
	}

	@keyframes waiting {
		50% {
			border-left-color: var(--hair);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.row.opening {
			animation: none;
		}
	}

	.row.read h2 {
		color: var(--ink-faint);
	}

	h2 {
		margin: 0;
		font-family: var(--display);
		font-size: 18px;
		font-weight: 700;
		line-height: 1.14;
		letter-spacing: -0.016em;
		text-wrap: pretty;
	}

	/* One line, always. A third of the authors in the archive are messy strings — some are
	   a whole production credit — and a row that grows to fit one wrecks the skim. */
	.by {
		display: flex;
		margin: 7px 0 0;
		font-size: 9.5px;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		white-space: nowrap;
		color: var(--ink-faint);
	}

	/* The author gives way a hundred times more readily than the outlet, which is where
	   the thing came from. Both still ellipse: some publications are named at a length no
	   phone has room for, and running off the paper is not a truer answer than a cut one. */
	.by .author {
		flex: 0 100 auto;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.by b {
		flex: 0 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		color: var(--ink);
		font-weight: 700;
	}

	/* Pushed to the far edge so the author gives way to it rather than to the row. */
	.kindle {
		flex: none;
		margin-left: auto;
		padding: 0 1px;
		font-weight: 700;
	}

	.kindle.sent {
		color: var(--ink);
		border-bottom: 1.5px solid var(--ink);
	}

	/* Dashed and faint: due to go, not gone. */
	.kindle.queued {
		color: var(--ink-faint);
		border-bottom: 1.5px dashed var(--ink-faint);
	}

	/* Only a search row has one. Two lines of it, because the point is the words around
	   the match and one line is not enough of them. */
	.found {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
		margin: 6px 0 0;
		font-size: 13px;
		line-height: 1.35;
		color: var(--ink-soft);
	}

	.found b {
		color: var(--ink);
		font-weight: 700;
	}

	.end {
		border-top: 1px solid var(--hair);
	}

	.by span:not(.kindle)::before {
		content: '\00a0\00a0·\00a0\00a0';
	}

	.note {
		padding: 1.4rem var(--gutter);
	}

	/* The archive is a tool rather than a paper: the headline, who ran it and when line up
	   in columns so a hundred rows can be read down rather than through. */
	.dense .row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 2px 14px;
		align-items: baseline;
		padding: 8px var(--gutter) 9px;
	}

	.dense .row > * {
		max-width: none;
	}

	.dense h2 {
		font-size: 15.5px;
		line-height: 1.2;
	}

	.dense .by {
		grid-column: 1;
		margin-top: 0;
	}

	.dense .when {
		grid-row: 1;
		grid-column: 2;
		flex: none;
		font-size: 9.5px;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--ink-faint);
		font-variant-numeric: tabular-nums;
	}

	.dense .found {
		grid-column: 1 / -1;
		-webkit-line-clamp: 1;
		line-clamp: 1;
		margin-top: 2px;
	}
</style>
