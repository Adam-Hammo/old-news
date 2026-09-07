<script lang="ts">
	import { markFinished, markOpened } from '#lib/api/client.ts';
	import type { Article } from '#lib/api/client.ts';
	import ArticleView from '#lib/components/Article.svelte';
	import { finished } from '#lib/finished.ts';
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';
	import { opened } from '#lib/opened.ts';

	let { article, view }: { article: Article; view: View } = $props();

	// Back to the list it was opened from, query and all — and named as it, or a reader in
	// the archive is offered a river they were never in.
	const back = $derived(links.list(view));
	const whence = $derived(view.archive ? 'Archive' : 'River');

	$effect(() => {
		// Recorded here rather than in `load`, which a hover prefetch also runs. Opening is a
		// fact about somebody reading, not about somebody nearly reading.
		const id = article.id;
		opened.add(id);
		markOpened(id);
	});

	function finish() {
		const id = article.id;
		if (finished.has(id)) return;
		finished.add(id);
		markFinished(id);
	}
</script>

<svelte:head><title>{article.title} — old news</title></svelte:head>

<ArticleView {article} {back} {whence} {finish} />
