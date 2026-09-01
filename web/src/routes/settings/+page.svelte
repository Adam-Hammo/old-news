<script lang="ts">
	import Feeds from '#lib/components/Feeds.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Settings — old news</title></svelte:head>

<div class="pane">
	<div class="top">
		<a href="/" class="up">&larr;&nbsp;&nbsp;River</a>
		<div class="hair"></div>
	</div>

	<div class="body">
		<p class="kicker">Settings</p>
		<Feeds feeds={data.feeds} sections={data.sections} />
	</div>
</div>

<style>
	.pane {
		display: flex;
		flex-direction: column;
		min-height: 100%;
		background: var(--paper-read);
	}

	.top {
		flex: none;
		padding: max(env(safe-area-inset-top), 0.75rem) var(--gutter) 0;
	}

	.up {
		display: inline-block;
		padding-bottom: 9px;
		font-size: 10.5px;
		font-weight: 600;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	.hair {
		height: 1px;
		background: var(--rule);
	}

	.top,
	.body {
		width: 100%;
		max-width: calc(var(--measure) + 2 * var(--gutter));
		margin-inline: auto;
	}

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
</style>
