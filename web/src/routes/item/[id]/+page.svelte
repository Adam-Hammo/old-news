<script lang="ts">
	import { markOpened } from '#lib/api/client.ts';
	import ArticleView from '#lib/components/Article.svelte';
	import { opened } from '#lib/opened.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const back = $derived(data.section ? `/?section=${encodeURIComponent(data.section)}` : '/');

	$effect(() => {
		// Recorded here rather than in `load`, which a hover prefetch also runs. Opening is a
		// fact about somebody reading, not about somebody nearly reading.
		const id = data.article.id;
		opened.add(id);
		void markOpened(id);
	});
</script>

<svelte:head><title>{data.article.title} — old news</title></svelte:head>

<ArticleView article={data.article} {back} />
