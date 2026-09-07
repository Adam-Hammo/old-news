<script lang="ts">
	import type { Listing, Shape } from '#lib/api/client.ts';
	import ArchiveHead from '#lib/components/ArchiveHead.svelte';
	import Facets from '#lib/components/Facets.svelte';
	import River from '#lib/components/River.svelte';
	import type { View } from '#lib/links.ts';
	import type { Snippet } from 'svelte';

	let {
		view,
		list,
		shape,
		total,
		selected,
		reading,
		pane = $bindable(),
		children,
	}: {
		view: View;
		list: Listing;
		shape: Shape;
		total: number | null;
		selected: string;
		reading: boolean;
		pane?: HTMLDivElement;
		children: Snippet;
	} = $props();
</script>

<div class="work" class:reading>
	<div class="head"><ArchiveHead {view} {total} /></div>
	<div class="rail scroller"><Facets {shape} {view} /></div>
	<div class="found scroller"><River page={list} {view} {selected} dense /></div>
	<!-- Over the results rather than beside them: the archive is a tool you search, and
	     an article read out of it is a detour rather than the other half of the screen. -->
	<div class="reading-pane scroller" bind:this={pane}>{@render children()}</div>
</div>

<style>
	.work {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		grid-template-columns: minmax(0, 1fr);
		grid-template-areas: 'head' 'found';
	}

	.head {
		grid-area: head;
		container-type: inline-size;
	}

	/* On a phone the rail is a strip under the header, so it is part of the header's row
	   rather than a column of its own. */
	.rail {
		grid-area: head;
		align-self: end;
		overflow-y: hidden;
	}

	.found,
	.reading-pane {
		grid-area: found;
		min-width: 0;
		container-type: inline-size;
	}

	.reading-pane {
		visibility: hidden;
		background: var(--paper-read);
	}

	/* Hidden rather than removed: a scroller that stops being displayed comes back at the
	   top, and getting back to where you were is the article's only navigation. */
	.work.reading > .found {
		visibility: hidden;
	}

	.work.reading > .reading-pane {
		visibility: visible;
	}

	@media (max-width: 61.99rem) {
		.work {
			grid-template-rows: auto auto minmax(0, 1fr);
			grid-template-areas: 'head' 'rail' 'found';
		}

		.rail {
			grid-area: rail;
			align-self: stretch;
			border-bottom: 1px solid var(--rule);
		}
	}

	@media (min-width: 62rem) {
		.work {
			grid-template-columns: 15rem minmax(0, 1fr);
			grid-template-areas: 'head head' 'rail found';
		}

		.rail {
			grid-area: rail;
			align-self: stretch;
			overflow-y: auto;
			border-right: 1px solid var(--rule);
		}
	}
</style>
