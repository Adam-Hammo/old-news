<script lang="ts">
	import Contents from '#lib/components/Contents.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>The Archive — old news</title></svelte:head>

{#if data.contents}
	<Contents held={data.contents} />
{/if}
