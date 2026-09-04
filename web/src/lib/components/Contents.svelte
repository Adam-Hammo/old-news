<script lang="ts">
	import type { Contents, Run } from '#lib/api/client.ts';
	import { stamp } from '#lib/format.ts';
	import * as links from '#lib/links.ts';
	import SearchBox from './SearchBox.svelte';

	let { held }: { held: Contents } = $props();

	// Shelved by how much trouble the publication is worth, because that is what decides
	// whether its back catalogue is worth walking. The wire's is not, so it folds.
	const SHELVES = [
		{ tier: 'kindle', label: 'Sent as a book' },
		{ tier: 'archive', label: 'Kept in full' },
		{ tier: 'wire', label: 'The wire', folded: true },
	];

	const counted = new Intl.NumberFormat();

	function runs(tier: string): Run[] {
		return held.feeds.filter((run) => !run.dropped && run.tier === tier);
	}

	const dropped = $derived(held.feeds.filter((run) => run.dropped));

	// The busiest month sets the bar every other one is drawn against, so the shelf reads
	// as a shape rather than as a column of numbers.
	const busiest = $derived(Math.max(1, ...held.months.map((volume) => volume.items)));
</script>

<article>
	<h1>The Archive</h1>
	<p class="say">
		Everything ever held &mdash; {counted.format(held.items)} pieces across {held.feeds.length} publications,
		including what has aged out of the river. Search it, or pick a shelf. Nothing here is one long
		list.
	</p>

	<SearchBox />

	<h2>By publication</h2>
	{#each SHELVES as shelf (shelf.tier)}
		{@const group = runs(shelf.tier)}
		{#if group.length}
			{#if shelf.folded}
				<details>
					<summary>
						<span class="folded">{shelf.label}</span>
						<span class="tally"
							>{counted.format(group.reduce((n, r) => n + r.items, 0))}</span
						>
					</summary>
					{@render runs_of(group)}
				</details>
			{:else}
				<h3>{shelf.label}</h3>
				{@render runs_of(group)}
			{/if}
		{/if}
	{/each}
	{#if dropped.length}
		<details>
			<summary>
				<span class="folded">No longer followed</span>
				<span class="tally">{counted.format(dropped.reduce((n, r) => n + r.items, 0))}</span
				>
			</summary>
			{@render runs_of(dropped)}
		</details>
	{/if}

	<h2>By month</h2>
	{#if held.months.length === 0}
		<p class="none label">Nothing held yet.</p>
	{:else}
		<ol class="months">
			{#each held.months as volume (volume.month)}
				<li>
					<a href={links.month(volume.month)}>
						<b>{links.volume(volume.month)}</b>
						<span class="bar" style="--fill: {(volume.items / busiest) * 100}%"></span>
						<span class="tally">{counted.format(volume.items)}</span>
					</a>
				</li>
			{/each}
		</ol>
	{/if}
</article>

{#snippet runs_of(group: Run[])}
	<ul class="feeds">
		{#each group.toSorted((a, b) => a.title.localeCompare(b.title)) as run (run.feed_id)}
			<li>
				<a href={links.feed(run.feed_id)}>
					<b>{run.title || run.url}</b>
					<span class="when">{stamp(run.latest)}</span>
					<span class="tally">{counted.format(run.items)}</span>
				</a>
			</li>
		{/each}
	</ul>
{/snippet}

<style>
	article {
		max-width: var(--measure);
		padding: 20px var(--gutter) 3rem;
	}

	h1 {
		margin: 0;
		font-family: var(--display);
		font-size: clamp(28px, 1.2rem + 2cqi, 40px);
		font-weight: 900;
		line-height: 1;
		letter-spacing: -0.022em;
	}

	.say {
		margin: 10px 0 26px;
		font-size: 15px;
		line-height: 1.5;
		color: var(--ink-soft);
		text-wrap: pretty;
	}

	h2 {
		margin: 30px 0 0;
		padding-bottom: 7px;
		font-family: var(--display);
		font-size: 19px;
		font-weight: 700;
		letter-spacing: -0.012em;
		border-bottom: 2px solid var(--ink);
	}

	h3,
	summary {
		margin: 20px 0 0;
		padding-bottom: 6px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.2em;
		text-transform: uppercase;
		color: var(--ink-faint);
		border-bottom: 1px solid var(--rule);
	}

	/* `display: flex` takes the native marker away, so the shelf gets its own — without
	   one a folded shelf reads as a heading with a number after it. */
	summary {
		display: flex;
		gap: 8px;
		justify-content: space-between;
		cursor: pointer;
	}

	summary::marker,
	summary::-webkit-details-marker {
		display: none;
		content: '';
	}

	summary .folded::before {
		content: '\25b8\00a0\00a0';
		display: inline-block;
	}

	details[open] summary .folded::before {
		transform: rotate(90deg);
	}

	ul,
	ol {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	li a {
		display: flex;
		gap: 12px;
		align-items: baseline;
		padding: 10px 0;
		border-top: 1px solid var(--hair);
	}

	li:first-child a {
		border-top: none;
	}

	li b {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--display);
		font-size: 16px;
		font-weight: 700;
	}

	.when {
		flex: none;
		font-size: 9.5px;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	/* Right-aligned on a fixed width so the counts form a column rather than a ragged edge. */
	.tally {
		flex: none;
		width: 4.5ch;
		text-align: right;
		font-size: 12px;
		font-variant-numeric: tabular-nums;
		color: var(--ink-soft);
	}

	/* How full a month is, drawn against the fullest one. The number is beside it, so this
	   only has to be comparable rather than readable. */
	.bar {
		flex: 1;
		height: 3px;
		min-width: 2rem;
		background: linear-gradient(
			to right,
			var(--rule) 0 var(--fill),
			var(--hair) var(--fill) 100%
		);
	}

	.months li b {
		flex: 0 1 9rem;
	}

	.none {
		padding: 1.4rem 0;
	}

	/* Two columns where there is room. Halving the scroll is the whole point of this
	   screen, and a shelf of forty publications is still a long way down one column. */
	@media (min-width: 62rem) {
		article {
			max-width: 58rem;
		}

		.feeds,
		.months {
			display: grid;
			grid-template-columns: 1fr 1fr;
			column-gap: 2.5rem;
		}

		/* The top row is two rows now, and the shelf's own rule already closes the gap. */
		.feeds li:nth-child(-n + 2) a,
		.months li:nth-child(-n + 2) a {
			border-top: none;
		}
	}
</style>
