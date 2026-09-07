<script lang="ts">
	import type { Listing } from '#lib/api/client.ts';
	import River from '#lib/components/River.svelte';
	import SectionStrip from '#lib/components/SectionStrip.svelte';
	import type { View } from '#lib/links.ts';
	import { pull, type Phase } from '#lib/pull.ts';
	import type { Snippet } from 'svelte';

	let {
		view,
		list,
		sections,
		selected,
		open,
		solo,
		refresh,
		column = $bindable(),
		pane = $bindable(),
		children,
	}: {
		view: View;
		list: Listing | null;
		sections: string[];
		selected: string;
		open: boolean;
		solo: boolean;
		refresh: () => Promise<void>;
		column?: HTMLDivElement;
		pane?: HTMLDivElement;
		children: Snippet;
	} = $props();

	let phase = $state<Phase>('');

	const note = $derived(
		phase === 'refreshing'
			? 'Refreshing…'
			: phase === 'ready'
				? 'Release to refresh'
				: 'Pull to refresh',
	);
</script>

<div class="shell" class:open class:solo>
	{#if list}
		<div
			class="list scroller"
			bind:this={column}
			data-pull={phase || undefined}
			use:pull={{ pulled: (next) => (phase = next), refresh }}
		>
			<div class="pulled">
				<p class="asking label">{note}</p>
				<SectionStrip {sections} current={view.section} />
				<River page={list} {view} {selected} />
			</div>
		</div>
	{/if}
	<div class="reading-pane scroller" bind:this={pane}>{@render children()}</div>
</div>

<style>
	/* The only place that knows how wide the window is. Both panes are fluid and render the
	   same at any width; what changes here is how many of them there are. */
	.shell {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		grid-template-rows: minmax(0, 1fr);
	}

	.shell > * {
		grid-area: 1 / 1;
		min-height: 0;
		/* So a pane's type scales with the pane it was given rather than with the window,
		   which is the whole reason neither of them measures the viewport. */
		container-type: inline-size;
	}

	.reading-pane {
		visibility: hidden;
		background: var(--paper-read);
	}

	/* Hidden rather than removed: a scroller that stops being displayed comes back at the
	   top, and getting back to where you were is the article's only navigation. */
	.shell.open > .list {
		visibility: hidden;
	}

	.shell.open > .reading-pane,
	.shell.solo > .reading-pane {
		visibility: visible;
	}

	/* What the pull moves. The line above it is outside the scroller's top edge, so it is
	   clipped until the drag brings it down. */
	.pulled {
		position: relative;
		transform: translateY(var(--pull, 0px));
		transition: transform 0.2s ease;
	}

	/* Under the finger it follows, so the spring back is the only part that is animated. */
	.list[data-pull] .pulled {
		transition: none;
	}

	.asking {
		position: absolute;
		inset-inline: 0;
		bottom: 100%;
		margin: 0;
		padding: 1.2rem var(--gutter);
		text-align: center;
	}

	@media (min-width: 62rem) {
		.shell.open {
			grid-template-columns: var(--column) minmax(0, 1fr);
		}

		.shell.open > .list {
			grid-area: 1 / 1;
			visibility: visible;
			border-right: 1px solid var(--rule);
		}

		.shell.open > .reading-pane {
			grid-area: 1 / 2;
		}
	}
</style>
