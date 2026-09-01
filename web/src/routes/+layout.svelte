<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import Masthead from '#lib/components/Masthead.svelte';
	import River from '#lib/components/River.svelte';
	import SectionStrip from '#lib/components/SectionStrip.svelte';
	import { report } from '#lib/report.ts';
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	let pane = $state<HTMLDivElement | undefined>();

	// Anything that is not the river gets the second pane: an article, or settings.
	const open = $derived(page.route.id !== '/');
	const selected = $derived(page.params.id ?? '');

	// A navigation that lands on an article and leaves the river on screen is the fault
	// worth catching. A paint that went stale is invisible from here and reports nothing,
	// which is the answer too: a wrong screen and no report means it was never the state.
	afterNavigate(() => {
		requestAnimationFrame(() => {
			if (!pane) return;
			const showing = getComputedStyle(pane).visibility === 'visible';
			if (showing !== open) {
				report('mismatch', `route=${page.route.id} pane=${showing}`, page.url.pathname);
			}
		});
	});
</script>

<div class="sheet">
	<Masthead section={data.section} updated={data.river.updated} />

	<div class="shell" class:open>
		<div class="list scroller">
			<SectionStrip sections={data.sections} current={data.section} />
			<River page={data.river} section={data.section} {selected} />
		</div>
		<div class="reading-pane scroller" bind:this={pane}>
			{@render children?.()}
		</div>
	</div>
</div>

<style>
	.sheet {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		width: 100%;
		max-width: var(--sheet);
		margin: 0 auto;
	}

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

	/* Hidden rather than removed: a scroller that stops being displayed comes back at the
	   top, and getting back to where you were is the article's only navigation. */
	.reading-pane {
		visibility: hidden;
	}

	.shell.open > .list {
		visibility: hidden;
	}

	.shell.open > .reading-pane {
		visibility: visible;
	}

	.reading-pane {
		background: var(--paper-read);
	}

	@media (min-width: 62rem) {
		/* The one place a width is known. The list column is the phone's browsing surface
		   at 430px rather than a second design, so it is fixed rather than fluid. */
		:global(body) {
			--gutter: 34px;
		}

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
