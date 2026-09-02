<script lang="ts">
	import Feeds from '#lib/components/Feeds.svelte';
	import Pane from '#lib/components/Pane.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Settings — old news</title></svelte:head>

<Pane back="/">
	<div class="body measured">
		<p class="kicker">Settings</p>
		<Feeds feeds={data.feeds} sections={data.sections} />
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
</style>
