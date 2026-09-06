<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import * as api from '#lib/api/client.ts';
	import ArchiveHead from '#lib/components/ArchiveHead.svelte';
	import Masthead from '#lib/components/Masthead.svelte';
	import River from '#lib/components/River.svelte';
	import SectionStrip from '#lib/components/SectionStrip.svelte';
	import { archived } from '#lib/links.ts';
	import { pull, type Phase } from '#lib/pull.ts';
	import { report } from '#lib/report.ts';
	import { STALE, whenStale } from '#lib/stale.ts';
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	let pane = $state<HTMLDivElement | undefined>();
	let column = $state<HTMLDivElement | undefined>();
	let phase = $state<Phase>('');

	// A refetched first page, held beside the load's rather than through it. A load that
	// throws takes the whole screen to the error page, and a poll that did not answer is
	// no reason to lose the river that is already on it.
	let latest = $state<api.Result | null>(null);
	let loaded = 0;
	let asking = false;

	const list = $derived(latest?.listing ?? data.list);
	const shelf = $derived(archived(data.view));
	const total = $derived(latest ? latest.total : data.total);

	// The contents page is a destination rather than a slice, so it takes the whole width.
	const solo = $derived(!list);
	// Anything that is not the list gets the second pane: an article, or settings. Never
	// both this and `solo` — open is the two-pane state and solo is the one-pane one.
	const open = $derived(page.route.id !== '/' && !solo);
	const selected = $derived(page.params.id ?? '');
	const note = $derived(
		phase === 'refreshing'
			? 'Refreshing…'
			: phase === 'ready'
				? 'Release to refresh'
				: 'Pull to refresh',
	);

	// Taking the load's clock is what subscribes this: a section change is a new first
	// page, and it outranks anything refetched against the old one.
	$effect(() => {
		loaded = data.at;
		latest = null;
	});

	async function refresh() {
		if (asking || !data.list) return;
		asking = true;
		// The view it was asked for. A refetch takes up to `TIMEOUT`, and a tap in that
		// window has already changed the screen — landing the river's rows under a shelf's
		// header. Identity is enough: every load builds a new one.
		const asked = data.view;
		try {
			const answer = await api.listing(fetch, asked);
			if (asked !== data.view) return;
			latest = answer;
			loaded = Date.now();
		} catch {
			// The river on screen is still the best answer there is.
		} finally {
			asking = false;
		}
	}

	// Never under a scrolled list: the pages after the first are refetched from the top,
	// so a refresh there would take the reader's place away to say nothing new.
	$effect(() => whenStale(() => Date.now() - loaded >= STALE && !column?.scrollTop, refresh));

	// A navigation that lands on an article and leaves the river on screen is the fault
	// worth catching. A paint that went stale is invisible from here and reports nothing,
	// which is the answer too: a wrong screen and no report means it was never the state.
	afterNavigate(() => {
		// The pane outlives the article in it, and nothing else puts the next one at its top.
		if (pane) pane.scrollTop = 0;
		requestAnimationFrame(() => {
			if (!pane) return;
			const showing = getComputedStyle(pane).visibility === 'visible';
			if (showing !== (open || solo)) {
				report('mismatch', `route=${page.route.id} pane=${showing}`, page.url.pathname);
			}
		});
	});
</script>

<div class="sheet">
	<Masthead
		view={data.view}
		inside={solo}
		updated={list?.updated ?? data.contents?.updated ?? null}
	/>

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
					{#if shelf}
						<ArchiveHead view={data.view} shelf={list.shelf} {total} />
					{:else}
						<SectionStrip sections={data.sections} current={data.view.section} />
					{/if}
					<River page={list} view={data.view} {selected} />
				</div>
			</div>
		{/if}
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

	.reading-pane {
		visibility: hidden;
		background: var(--paper-read);
	}

	/* Hidden rather than removed: a scroller that stops being displayed comes back at the
	   top, and getting back to where you were is the article's only navigation. */
	.shell.open > .list {
		visibility: hidden;
	}

	.shell.open > .reading-pane {
		visibility: visible;
	}

	/* No list to sit beside, so the pane is the screen. */
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
