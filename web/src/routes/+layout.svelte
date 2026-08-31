<script lang="ts">
	import { page } from '$app/state';
	import Masthead from '#lib/components/Masthead.svelte';
	import River from '#lib/components/River.svelte';
	import SectionStrip from '#lib/components/SectionStrip.svelte';
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const reading = $derived(page.route.id?.startsWith('/item') ?? false);
	const selected = $derived(page.params.id ?? '');
</script>

<div class="sheet">
	<Masthead section={data.section} updated={data.river.updated} />

	<div class="shell" class:reading>
		<div class="list scroller">
			<SectionStrip sections={data.sections} current={data.section} />
			<River page={data.river} section={data.section} {selected} />
		</div>
		<div class="reading-pane scroller">
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

	.shell.reading > .list {
		visibility: hidden;
	}

	.shell.reading > .reading-pane {
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

		.shell.reading {
			grid-template-columns: var(--column) minmax(0, 1fr);
		}

		.shell.reading > .list {
			grid-area: 1 / 1;
			visibility: visible;
			border-right: 1px solid var(--rule);
		}

		.shell.reading > .reading-pane {
			grid-area: 1 / 2;
		}
	}
</style>
