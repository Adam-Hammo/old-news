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
	// reached, and clicking a line adds the term that would narrow it.
	const groups = $derived([
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
		{
			label: 'You',
			rows: STATES.map(({ name, label }) => ({
				label,
				items: shape.states.find((count: Count) => count.name === name)?.items ?? 0,
				term: `is:${name}`,
			})),
		},
	]);

	function shown(rows: { items: number }[]): boolean {
		return rows.some((row) => row.items > 0);
	}
</script>

<nav aria-label="What the query reached">
	{#each groups as group (group.label)}
		{#if shown(group.rows)}
			<section>
				<h2>
					{group.label}
					<i>{counted.format(group.rows.filter((row) => row.items > 0).length)}</i>
				</h2>
				<ul>
					{#each group.rows as row (row.term)}
						{#if row.items > 0}
							{@const on = links.carries(view, row.term)}
							<li>
								<a
									href={links.toggled(view, row.term)}
									class:on
									aria-label={on
										? `Stop narrowing to ${row.label}`
										: `Narrow to ${row.label}`}
								>
									<b>{row.label}</b>
									<span>{counted.format(row.items)}</span>
									{#if on}<em aria-hidden="true">×</em>{/if}
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
	/* Each group takes the height it needs and no more than a third of the screen, so
	   every heading is on it. Forty-one publications used to take the lot and push the
	   third group off the bottom, and the rail scrolling as a whole did not help: what
	   you wanted was the group you could not see. */
	nav {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 12px var(--gutter) 18px;
	}

	h2 i {
		float: right;
		font-style: normal;
		font-weight: 400;
		font-variant-numeric: tabular-nums;
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
		max-height: 30vh;
		overflow-y: auto;
		scrollbar-width: thin;
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

	/* Already in the query, so the click takes it off again. The count stays — it is what
	   this line reaches on its own, which is a thing worth still being able to read. */
	li a.on {
		color: var(--ink);
	}

	li a.on span {
		color: var(--ink);
	}

	li em {
		flex: none;
		font-style: normal;
		font-weight: 700;
		font-size: 12px;
		line-height: 1;
	}

	li a.on b {
		font-weight: 700;
	}

	@media (max-width: 61.99rem) {
		/* No room for a rail, so each group is its own scrolling row — in the same order
		   the rail has them, each keeping its name. One row for all three put `You` five
		   thousand pixels along, behind every publication there is. */
		nav {
			gap: 4px;
			padding: 7px 0;
		}

		/* The gutter is on what is inside, not on the scroller: `position: sticky` resolves
		   against the padding box, so a padded row slid its heading out to the screen edge
		   as soon as it was scrolled. */
		section {
			display: flex;
			align-items: center;
			gap: 8px;
			overflow-x: auto;
			scrollbar-width: none;
		}

		section::-webkit-scrollbar {
			display: none;
		}

		/* Sticky, so the row still says what it is once it has been scrolled along. */
		h2 {
			position: sticky;
			left: 0;
			z-index: 1;
			margin: 0;
			padding: 0 8px 0 var(--gutter);
			border-bottom: 0;
			white-space: nowrap;
			background: var(--paper);
		}

		/* How many values there are is a rail answer. On a strip it is one more number
		   beside a row of them. */
		h2 i {
			display: none;
		}

		ul {
			display: flex;
			gap: 6px;
			max-height: none;
			overflow-y: visible;
			padding-right: var(--gutter);
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
