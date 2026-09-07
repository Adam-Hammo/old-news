<script lang="ts">
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';
	import SearchBox from './SearchBox.svelte';

	let { view, total = null }: { view: View; total?: number | null } = $props();

	const counted = new Intl.NumberFormat();
</script>

<nav>
	<a href={links.contents()} class="back">&larr;&nbsp; Archive</a>
	<!-- The field itself, carrying the query: narrowing is editing what is there rather
	     than going back for a fresh box. -->
	<div class="again"><SearchBox terms={view.q} /></div>
	<span class="tally">{counted.format(total ?? 0)} {total === 1 ? 'piece' : 'pieces'}</span>
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
	   a field showing four characters of the query is not a field. */
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

	.tally {
		flex: none;
		color: var(--ink-faint);
		font-variant-numeric: tabular-nums;
	}

	.edge {
		height: 1px;
		background: var(--rule);
	}
</style>
