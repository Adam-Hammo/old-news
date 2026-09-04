<script lang="ts">
	import { markFinished, markOpened } from '#lib/api/client.ts';
	import ArticleView from '#lib/components/Article.svelte';
	import { finished } from '#lib/finished.ts';
	import { opened } from '#lib/opened.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const back = $derived(data.section ? `/?section=${encodeURIComponent(data.section)}` : '/');

	$effect(() => {
		// Recorded here rather than in `load`, which a hover prefetch also runs. Opening is a
		// fact about somebody reading, not about somebody nearly reading.
		const id = data.article.id;
		opened.add(id);
		markOpened(id);
	});

	function finish() {
		const id = data.article.id;
		if (finished.has(id)) return;
		finished.add(id);
		markFinished(id);
	}
</script>

<svelte:head><title>{data.article.title} — old news</title></svelte:head>

<ArticleView article={data.article} {back} {finish} />
