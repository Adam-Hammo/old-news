<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import * as api from '#lib/api/client.ts';
	import type { River as Page } from '#lib/api/client.ts';
	import Masthead from '#lib/components/Masthead.svelte';
	import River from '#lib/components/River.svelte';
	import SectionStrip from '#lib/components/SectionStrip.svelte';
	import { pull, type Phase } from '#lib/pull.ts';
	import { report } from '#lib/report.ts';
	import { STALE, whenStale } from '#lib/stale.ts';
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	let pane = $state<HTMLDivElement | undefined>();
	let list = $state<HTMLDivElement | undefined>();
	let phase = $state<Phase>('');

	// A refetched first page, held beside the load's rather than through it. A load that
	// throws takes the whole screen to the error page, and a poll that did not answer is
	// no reason to lose the river that is already on it.
	let latest = $state<Page | null>(null);
	let loaded = 0;
	let asking = false;

	const river = $derived(latest ?? data.river);

	// Anything that is not the river gets the second pane: an article, or settings.
	const open = $derived(page.route.id !== '/');
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
		if (asking) return;
		asking = true;
		try {
			latest = await api.river(fetch, { section: data.section });
			loaded = Date.now();
		} catch {
			// The river on screen is still the best answer there is.
		} finally {
			asking = false;
		}
	}

	// Never under a scrolled list: the pages after the first are refetched from the top,
	// so a refresh there would take the reader's place away to say nothing new.
	$effect(() => whenStale(() => Date.now() - loaded >= STALE && !list?.scrollTop, refresh));

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
	<Masthead section={data.section} updated={river.updated} />

	<div class="shell" class:open>
		<div
			class="list scroller"
			bind:this={list}
			data-pull={phase || undefined}
			use:pull={{ pulled: (next) => (phase = next), refresh }}
		>
			<div class="pulled">
				<p class="asking">{note}</p>
				<SectionStrip sections={data.sections} current={data.section} />
				<River page={river} section={data.section} {selected} />
			</div>
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
		color: var(--ink-faint);
		font-size: 10.5px;
		font-weight: 600;
		letter-spacing: 0.12em;
		text-transform: uppercase;
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
