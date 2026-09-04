<script lang="ts">
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';
	import SearchBox from './SearchBox.svelte';

	let {
		view,
		shelf,
		total = null,
	}: { view: View; shelf: string; total?: number | null } = $props();

	// A publication names itself only from the archive, which knows its title. A month
	// names itself from the URL, so both halves can be on screen at once.
	const named = $derived(
		[shelf, view.month ? links.volume(view.month) : ''].filter(Boolean).join(', '),
	);

	// One filter, and only where it changes anything: a month is mostly wire, and a
	// publication is one tier already.
	const sifted = $derived(Boolean(view.month) && !view.feed);
	const showing = $derived(!view.tier);

	const counted = new Intl.NumberFormat();
</script>

<nav>
	<a href={links.contents()} class="back">&larr;&nbsp; Contents</a>
	{#if view.q}
		<!-- The name slot is the field itself, so narrowing a search does not mean going back. -->
		<div class="again"><SearchBox terms={view.q} /></div>
		<span class="tally">{counted.format(total ?? 0)} {total === 1 ? 'match' : 'matches'}</span>
	{:else}
		<b class="named">{named}</b>
	{/if}
	{#if sifted}
		<a href={links.wire(view, !showing)} class="sift">
			{showing ? 'Without the wire' : 'With the wire'}
		</a>
	{/if}
</nav>
<div class="edge"></div>

<style>
	nav {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		align-items: baseline;
		padding: 9px var(--gutter);
		font-size: 10.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		background: var(--paper);
	}

	.back {
		flex: none;
		color: var(--ink-faint);
	}

	/* Its own line by default: at 430px the back link and the count already fill one, and
	   a field showing four characters of the search is not a field. */
	.again {
		flex: 1 1 100%;
		min-width: 0;
		order: 1;
	}

	@container (min-width: 34rem) {
		.again {
			flex: 1 1 14rem;
			order: 0;
		}
	}

	/* The shelf's own name, which is the one thing on this line that is not a control. */
	.named {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 700;
		color: var(--ink);
	}

	.tally,
	.sift {
		flex: none;
		color: var(--ink-faint);
	}

	.tally {
		font-variant-numeric: tabular-nums;
	}

	.edge {
		height: 1px;
		background: var(--rule);
	}
</style>
