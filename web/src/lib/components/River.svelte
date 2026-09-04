<script lang="ts">
	import { navigating } from '$app/state';
	import * as api from '#lib/api/client.ts';
	import type { Entry, River } from '#lib/api/client.ts';
	import { finished } from '#lib/finished.ts';
	import * as links from '#lib/links.ts';
	import { opened } from '#lib/opened.ts';
	import { whenVisible } from '#lib/visible.ts';

	let {
		page,
		section,
		selected,
		archive = false,
	}: { page: River; section: string; selected: string; archive?: boolean } = $props();

	const view = $derived({ section, archive });

	// Pages fetched after the first, which the layout's load knows nothing about.
	let extra = $state<Entry[]>([]);
	let cursor = $state('');
	let loading = $state(false);
	let failed = $state(false);

	$effect(() => {
		// Reading `page.cursor` is what subscribes this, so a new first page — a section
		// change, or an invalidation — replaces whatever had been appended to the old one.
		extra = [];
		cursor = page.cursor;
		failed = false;
	});

	const entries = $derived([...page.entries, ...extra]);

	async function more() {
		if (!cursor || loading) return;
		loading = true;
		try {
			const next = await api.river(fetch, {
				section,
				after: cursor,
				archive: archive ? 1 : undefined,
			});
			extra = [...extra, ...next.entries];
			cursor = next.cursor;
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

<ol>
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
			</a>
		</li>
	{/each}
</ol>

{#if entries.length === 0}
	<p class="note label">{archive ? 'Nothing in the archive yet.' : 'Nothing here yet.'}</p>
{:else if failed}
	<p class="note label"><button onclick={more}>Could not load more. Try again.</button></p>
{:else if cursor}
	<div use:whenVisible={more} class="note label more">{loading ? 'Loading…' : ''}</div>
{:else if !archive}
	<!-- The end of the river is where the door has to be, or ageing out loses things. -->
	<p class="note label end">
		<a href={links.archive(view, true)}>Older stories are in the archive &nbsp;&rarr;</a>
	</p>
{:else}
	<p class="note label end">
		<a href={links.archive(view, false)}>&larr;&nbsp; Back to the river</a>
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

	/* The author is the only part allowed to give way. The outlet is where it came from,
	   and a row that cut that would be lying. */
	.by .author {
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.by b {
		flex: none;
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

	.end {
		border-top: 1px solid var(--hair);
	}

	.by span:not(.kindle)::before {
		content: '\00a0\00a0·\00a0\00a0';
	}

	.note {
		padding: 1.4rem var(--gutter);
	}
</style>
