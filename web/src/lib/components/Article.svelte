<script lang="ts">
	import type { Article } from '#lib/api/client.ts';
	import Pane from '#lib/components/Pane.svelte';
	import { dateline } from '#lib/format.ts';
	import { render } from '#lib/markdown.ts';
	import { whenVisible } from '#lib/visible.ts';

	let { article, back, finish }: { article: Article; back: string; finish: () => void } =
		$props();

	let sheet = $state<HTMLDialogElement | undefined>();
	let picked = $state<string | null>(null);

	$effect(() => {
		// A different article opens on its own fuller reading.
		void article.id;
		picked = null;
	});

	const source = $derived(picked ?? article.reading);
	const text = $derived(source === 'feed' ? article.feed_body : article.page_body);
	const both = $derived(Boolean(article.feed_body && article.page_body));

	const body = $derived(render(text));
	const dated = $derived(dateline(article.published_at ?? article.first_seen_at));
	const origin = $derived(new URL(article.url).hostname.replace(/^www\./, ''));
</script>

<Pane {back}>
	<article class="measured">
		{#if article.section}<p class="kicker">{article.section}</p>{/if}
		<h1>{article.title}</h1>

		<div class="hair"></div>
		<p class="by">
			<span class="outlet">{article.outlet}</span>
			{#if article.author}<span>{article.author}</span>{/if}
			{#if dated}<span>{dated}</span>{/if}
			{#if article.versions > 1 || both}
				<span class="meta">
					{#if article.versions > 1}<em>v{article.versions} of {article.versions}</em
						>{/if}
					{#if both}
						<button aria-pressed={source === 'feed'} onclick={() => (picked = 'feed')}>
							Feed
						</button>
						<button aria-pressed={source === 'page'} onclick={() => (picked = 'page')}>
							Web
						</button>
					{/if}
				</span>
			{/if}
		</p>
		<div class="thin"></div>

		{#if article.lead}
			<!-- Served from the archive, so it outlives the publisher's copy. -->
			<figure class="lead"><img src={article.lead} alt={article.lead_alt} /></figure>
		{/if}

		{#if text}
			<!-- Scrubbed in #lib/markdown.ts, the one place publisher html is let through. -->
			<!-- eslint-disable-next-line svelte/no-at-html-tags -->
			<div class="body">{@html body}</div>
		{:else}
			<p class="pending label">No text has been read out of this one yet.</p>
		{/if}
		<!-- Reaching this is what "read" means, as against opening the thing. -->
		<div use:whenVisible={finish} class="finish"></div>
	</article>

	<div class="cap"></div>
	<nav class="bar">
		<a href={back}>&larr;&nbsp; Back to the river</a>
		<span class="divider"></span>
		<button onclick={() => sheet?.showModal()} aria-label="Article actions"
			>&#183;&#183;&#183;</button
		>
	</nav>
</Pane>

<dialog bind:this={sheet} onclick={(event) => event.target === sheet && sheet?.close()}>
	<p class="sheethead">This article</p>
	<div class="hair"></div>
	<ul>
		<li>
			<a href={article.url} target="_blank" rel="noreferrer noopener">
				<span>Read the original</span><em>{origin} &nbsp;&#8599;</em>
			</a>
		</li>
		{#if article.comments_url}
			<li>
				<a href={article.comments_url} target="_blank" rel="noreferrer noopener">
					<span>Comments</span>
				</a>
			</li>
		{/if}
		<li>
			<button
				onclick={() => {
					finish();
					sheet?.close();
				}}
			>
				<span>Mark as read</span><em>keeps it off the Kindle</em>
			</button>
		</li>
		<li>
			<button onclick={() => navigator.clipboard?.writeText(article.url)}>
				<span>Copy link</span>
			</button>
		</li>
		<li class="close">
			<button onclick={() => sheet?.close()}>Close</button>
		</li>
	</ul>
</dialog>

<style>
	article {
		flex: 1;
		padding: 0 var(--gutter) calc(61px + 1.5rem);
	}

	.thin {
		height: 1px;
		background: var(--hair);
	}

	/* `whenVisible` fires 600px early, which for the last screen of an article is the
	   point: the bottom is in view long before the very last line is. */
	.finish {
		height: 1px;
	}

	/* Held to the measure like everything else, and given its own height rather than a
	   ratio: the archive keeps one rendition and its shape is the publisher's. */
	.lead {
		margin: 1.4rem 0 0;
	}

	.lead img {
		display: block;
		width: 100%;
		height: auto;
	}

	.kicker {
		margin: 0;
		padding: 17px 0 10px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.2em;
		text-transform: uppercase;
	}

	h1 {
		margin: 0;
		padding-top: 17px;
		font-family: var(--display);
		font-size: clamp(30px, 1.1rem + 2.2cqi, 42px);
		font-weight: 700;
		line-height: 1.04;
		letter-spacing: -0.025em;
		text-wrap: pretty;
	}

	.kicker + h1 {
		padding-top: 0;
	}

	.by {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 7px;
		margin: 0;
		padding: 8px 0;
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	.by .outlet {
		color: var(--ink);
		font-weight: 700;
		border-bottom: 1px solid var(--underline);
	}

	.by span + span::before {
		content: '·\00a0\00a0';
	}

	.by .meta::before {
		content: none;
	}

	.meta {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-left: auto;
	}

	.by em {
		font-style: normal;
	}

	.meta button {
		font: inherit;
		letter-spacing: inherit;
		text-transform: inherit;
		color: var(--ink-faint);
	}

	.meta button[aria-pressed='true'] {
		color: var(--ink);
		font-weight: 700;
		border-bottom: 1px solid var(--underline);
	}

	.body {
		padding-top: 16px;
	}

	.pending {
		padding-top: 2rem;
	}

	/* Justified with hyphens, which is the whole reason the column is measured. */
	.body :global(p) {
		margin: 0 0 15px;
		font-size: clamp(16.5px, 1rem + 0.1cqi, 17px);
		line-height: 1.62;
		text-align: justify;
		hyphens: auto;
	}

	.body :global(h1),
	.body :global(h2),
	.body :global(h3) {
		margin: 1.7em 0 0.5em;
		font-family: var(--display);
		font-size: 1.15rem;
		font-weight: 700;
		line-height: 1.2;
	}

	.body :global(a) {
		border-bottom: 1px solid var(--underline);
	}

	.body :global(img) {
		max-width: 100%;
		height: auto;
	}

	.body :global(blockquote) {
		margin: 1.3em 0;
		padding-left: 1.1em;
		border-left: 2px solid var(--hair);
		color: var(--ink-soft);
	}

	.body :global(pre) {
		overflow-x: auto;
		padding: 0.85em 1em;
		background: var(--well);
		font-size: 0.82rem;
	}

	.body :global(figcaption) {
		font-size: 12.5px;
		line-height: 1.45;
		color: var(--ink-soft);
	}

	.body :global(hr) {
		border: 0;
		border-top: 1px solid var(--hair);
	}

	.cap {
		position: sticky;
		bottom: 58px;
		height: 3px;
		background: var(--rule);
	}

	.bar {
		position: sticky;
		bottom: 0;
		display: flex;
		align-items: center;
		height: calc(58px + env(safe-area-inset-bottom));
		padding-bottom: env(safe-area-inset-bottom);
		background: var(--paper-read);
	}

	.bar a,
	.bar button {
		flex-grow: 1;
		text-align: center;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.12em;
		text-transform: uppercase;
	}

	.bar a {
		font-weight: 700;
	}

	.bar button {
		letter-spacing: 0.2em;
		font-size: 15px;
	}

	.divider {
		width: 1px;
		height: 18px;
		background: var(--hair);
	}

	/* A modal dialog is laid out against the viewport, but the app is a sheet centred in
	   it, so the corner the control sits in has to be worked out rather than asked for. */
	dialog {
		margin: auto max(0px, (100vw - var(--sheet)) / 2) 0 auto;
	}

	dialog a,
	dialog li button {
		justify-content: space-between;
		text-transform: uppercase;
	}

	dialog em {
		font-style: normal;
		font-size: 11px;
		font-weight: 400;
		letter-spacing: 0.02em;
		text-transform: none;
		color: var(--ink-faint);
	}

	.close button {
		justify-content: center;
		border-bottom: 0;
		letter-spacing: 0.14em;
		font-weight: 400;
		color: var(--ink-faint);
	}
</style>
