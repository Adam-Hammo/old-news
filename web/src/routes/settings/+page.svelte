<script lang="ts">
	import Config from '#lib/components/Config.svelte';
	import Feeds from '#lib/components/Feeds.svelte';
	import Pane from '#lib/components/Pane.svelte';
	import Polling from '#lib/components/Polling.svelte';
	import Publishers from '#lib/components/Publishers.svelte';
	import { href, TABS } from '#lib/tabs.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Settings — old news</title></svelte:head>

<Pane back="/" whence="River">
	<div class="body measured">
		<p class="kicker">Settings</p>
		<!-- Scrolls at 320px, where four of these do not fit on one line. -->
		<nav>
			{#each TABS as tab (tab.id)}
				<a href={href(tab.id)} class:current={tab.id === data.tab}>{tab.label}</a>
			{/each}
		</nav>
		<div class="hair"></div>

		{#if data.tab === 'feeds'}
			<Feeds feeds={data.feeds} sections={data.sections} />
		{:else if data.tab === 'polling'}
			<Polling feeds={data.polling} />
		{:else if data.tab === 'publishers'}
			<Publishers hosts={data.publishers} />
		{:else}
			<Config config={data.config} />
		{/if}
	</div>
</Pane>

<style>
	.body {
		flex: 1;
		padding: 0 var(--gutter) 3rem;
	}

	.kicker {
		margin: 0;
		padding: 17px 0 0;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.2em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	nav {
		display: flex;
		gap: 18px;
		margin-top: 14px;
		padding-bottom: 9px;
		overflow-x: auto;
		white-space: nowrap;
		scrollbar-width: none;
		font-size: 10.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
	}

	nav::-webkit-scrollbar {
		display: none;
	}

	nav a {
		color: var(--ink-faint);
	}

	nav a.current {
		color: var(--ink);
		font-weight: 700;
	}

	/* Nothing under the rule until the page has one, or every tab starts with a gap the
	   size of a heading that is not there. */
	.body :global(section h2:first-child) {
		padding-top: 22px;
	}
</style>
