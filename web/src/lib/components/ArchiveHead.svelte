<script lang="ts">
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';
	import SearchBox from './SearchBox.svelte';

	let { view, total = null }: { view: View; total?: number | null } = $props();

	const counted = new Intl.NumberFormat();
	const narrowing = $derived(links.applied(view));
</script>

<nav>
	{#if view.q}
		<a href={links.archive()} class="back">&larr;&nbsp; Everything</a>
	{/if}
	<!-- The field itself, carrying the query: narrowing is editing what is there rather
	     than going back for a fresh box. -->
	<div class="again"><SearchBox terms={view.q} /></div>
	<span class="tally">{counted.format(total ?? 0)} {total === 1 ? 'piece' : 'pieces'}</span>
</nav>
{#if narrowing.length}
	<!-- What is applied, as words. The rail cannot carry this: once the query is inside a
	     year the rail lists that year's months, so the row you drilled through is gone. -->
	<p class="narrowed">
		<span class="label">Narrowed by</span>
		{#each narrowing as one (one.label)}
			<a href={links.search(one.without)} aria-label="Stop narrowing by {one.label}">
				{one.label}<em aria-hidden="true">×</em>
			</a>
		{/each}
	</p>
{/if}
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

	.narrowed {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
		margin: 0;
		padding: 0 var(--gutter) 9px;
		background: var(--paper);
	}

	.narrowed .label {
		margin-right: 2px;
	}

	.narrowed a {
		display: inline-flex;
		gap: 7px;
		align-items: baseline;
		padding: 4px 8px;
		font-size: 10.5px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--paper);
		background: var(--ink);
	}

	.narrowed em {
		font-style: normal;
		font-weight: 400;
		font-size: 12px;
		line-height: 1;
	}

	.edge {
		height: 1px;
		background: var(--rule);
	}
</style>
