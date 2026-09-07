<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import * as api from '#lib/api/client.ts';
	import ArchiveShell from '#lib/components/ArchiveShell.svelte';
	import Masthead from '#lib/components/Masthead.svelte';
	import RiverShell from '#lib/components/RiverShell.svelte';
	import { watching } from '#lib/progress.ts';
	import { report } from '#lib/report.ts';
	import { STALE, whenStale } from '#lib/stale.ts';
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	let pane = $state<HTMLDivElement | undefined>();
	let column = $state<HTMLDivElement | undefined>();
	// How far down the article the reader has got, which the masthead's rule draws instead
	// of a scrollbar. Only an article has one: nothing else is a thing you are partway through.
	let through = $state(1);

	// A refetched first page, held beside the load's rather than through it. A load that
	// throws takes the whole screen to the error page, and a poll that did not answer is
	// no reason to lose the river that is already on it.
	let latest = $state<api.Result | null>(null);
	let loaded = 0;
	let asking = false;

	const list = $derived(latest?.listing ?? data.list);
	const total = $derived(latest ? latest.total : data.total);

	// Anything that is not the list gets the second pane: an article, or settings.
	const open = $derived(page.route.id !== '/' && page.route.id !== '/archive');
	const solo = $derived(!list);
	const selected = $derived(page.params.id ?? '');
	const reading = $derived(Boolean(page.route.id?.endsWith('/item/[id]')));

	// Re-attached on every navigation: the pane outlives the article in it, and what is in
	// it is what decides whether there is anything to scroll.
	$effect(() => {
		void page.url.pathname;
		if (!pane) return;
		return watching(pane, (share) => (through = share));
	});

	// Taking the load's clock is what subscribes this: a section change is a new first
	// page, and it outranks anything refetched against the old one.
	$effect(() => {
		loaded = data.at;
		latest = null;
	});

	async function refresh() {
		if (asking || data.archive || !data.list) return;
		asking = true;
		// The view it was asked for. A refetch takes up to `TIMEOUT`, and a tap in that
		// window has already changed the screen — landing the river's rows under a query's
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

	// The river only, and never under a scrolled list: the pages after the first are
	// refetched from the top, so a refresh there would take the reader's place away to say
	// nothing new. The archive is not polled and has no `column` to ask, so it is left out
	// rather than guarded — a refetch there would drop every page appended to it.
	$effect(() => whenStale(() => Date.now() - loaded >= STALE && !column?.scrollTop, refresh));

	// A navigation that lands on an article and leaves the list on screen is the fault
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

<div class="sheet" class:reading>
	<Masthead
		view={data.view}
		updated={list?.updated ?? data.shape?.updated ?? null}
		through={reading ? through : 1}
	/>

	<!-- Two screens, and the path chose which before the data was fetched. -->
	{#if data.archive && data.shape && list}
		<ArchiveShell
			view={data.view}
			{list}
			shape={data.shape}
			{total}
			{selected}
			{reading}
			bind:pane
		>
			{@render children?.()}
		</ArchiveShell>
	{:else}
		<RiverShell
			view={data.view}
			{list}
			sections={data.sections}
			{selected}
			{open}
			{solo}
			{refresh}
			bind:column
			bind:pane
		>
			{@render children?.()}
		</RiverShell>
	{/if}
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

	/* The masthead's rule is the gauge on an article, so a second one down the edge says
	   the same thing twice. Only on an article: the rule does not move for settings, and a
	   scroller with neither a bar nor a gauge says nothing at all. */
	.sheet.reading :global(.reading-pane) {
		scrollbar-width: none;
	}

	.sheet.reading :global(.reading-pane::-webkit-scrollbar) {
		display: none;
	}

	@media (min-width: 62rem) {
		/* The one place a width is known. The river's list column is the phone's browsing
		   surface at 430px rather than a second design, so it is fixed rather than fluid. */
		:global(body) {
			--gutter: 34px;
		}
	}
</style>
