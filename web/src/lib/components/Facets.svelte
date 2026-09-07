<script lang="ts">
	import type { Count, Shape } from '#lib/api/client.ts';
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';

	let { shape, view }: { shape: Shape; view: View } = $props();

	const counted = new Intl.NumberFormat();

	// Read is a tap on a headline; finished is the bottom of the article. The other two
	// are the same two facts read the other way round, and one of each pair is enough.
	const STATES = [
		{ name: 'unread', label: 'Never opened' },
		{ name: 'read', label: 'Opened' },
		{ name: 'finished', label: 'Read to the end' },
	];

	// The rail reports rather than remembers: what it draws is the shape of what the query
	// reached, and clicking a line adds the term that would narrow it. Shortest group
	// first, because on a phone these are one scrolling strip and forty-one publications
	// ahead of three states would bury them.
	const groups = $derived([
		{
			label: 'You',
			rows: STATES.map(({ name, label }) => ({
				label,
				items: shape.states.find((count: Count) => count.name === name)?.items ?? 0,
				term: `is:${name}`,
			})),
		},
		{
			label: 'When',
			rows: shape.months.map((count: Count) => ({
				label: links.volume(count.name),
				items: count.items,
				term: links.within(count.name),
			})),
		},
		{
			label: 'Publication',
			rows: shape.publications.map((count: Count) => ({
				label: count.name,
				items: count.items,
				term: links.from(count.name),
			})),
		},
	]);

	function already(term: string): boolean {
		return view.q.includes(term);
	}

	function shown(rows: { items: number }[]): boolean {
		return rows.some((row) => row.items > 0);
	}
</script>

<nav>
	{#each groups as group (group.label)}
		{#if shown(group.rows)}
			<section>
				<h2>{group.label}</h2>
				<ul>
					{#each group.rows as row (row.term)}
						{#if row.items > 0}
							<li>
								<a href={links.and(view, row.term)} class:on={already(row.term)}>
									<b>{row.label}</b>
									<span>{counted.format(row.items)}</span>
								</a>
							</li>
						{/if}
					{/each}
				</ul>
			</section>
		{/if}
	{/each}
</nav>

<style>
	/* Scrolls on its own: forty-one publications is longer than any screen, and the
	   results beside it have their own scroll to keep. */
	nav {
		display: flex;
		flex-direction: column;
		gap: 18px;
		padding: 12px var(--gutter) 3rem;
	}

	h2 {
		margin: 0 0 6px;
		padding-bottom: 5px;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.18em;
		text-transform: uppercase;
		color: var(--ink-faint);
		border-bottom: 1px solid var(--rule);
	}

	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	li a {
		display: flex;
		gap: 10px;
		align-items: baseline;
		justify-content: space-between;
		padding: 4px 0;
		color: var(--ink-soft);
	}

	li b {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12.5px;
		font-weight: 400;
	}

	li span {
		flex: none;
		font-size: 10.5px;
		font-variant-numeric: tabular-nums;
		color: var(--ink-faint);
	}

	/* Already in the query. Still a link, because adding it twice is harmless and
	   greying it out would hide where the number came from. */
	li a.on {
		color: var(--ink);
	}

	li a.on b {
		font-weight: 700;
	}

	@media (max-width: 61.99rem) {
		/* No room for a rail, so the groups run across as one scrolling strip. */
		nav {
			flex-direction: row;
			gap: 0;
			overflow-x: auto;
			scrollbar-width: none;
			padding: 8px var(--gutter);
		}

		nav::-webkit-scrollbar {
			display: none;
		}

		h2 {
			display: none;
		}

		ul {
			display: flex;
			gap: 6px;
		}

		li a {
			gap: 6px;
			padding: 5px 8px;
			border: 1px solid var(--hair);
			white-space: nowrap;
		}

		li a.on {
			border-color: var(--rule);
		}

		li b {
			font-size: 11px;
		}
	}
</style>
