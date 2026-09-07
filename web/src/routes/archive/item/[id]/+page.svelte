<script lang="ts">
	import Reading from '#lib/components/Reading.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<Reading article={data.article} view={data.view} />
