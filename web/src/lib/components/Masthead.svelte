<script lang="ts">
	import { stamp, today } from '#lib/format.ts';
	import * as links from '#lib/links.ts';
	import type { View } from '#lib/links.ts';

	let {
		view = links.NOWHERE,
		inside = false,
		updated = null,
	}: { view?: View; inside?: boolean; updated?: string | null } = $props();

	const polled = $derived(stamp(updated));
	const dated = today();

	// Anywhere in the archive, the nameplate says so and the crossing goes back to the
	// river. The foot of the river carries a door too, but reaching it means paging to
	// the end of the list.
	const archive = $derived(inside || links.archived(view));
</script>

<header>
	<div class="line">
		<a href={links.list({ ...links.NOWHERE, section: view.section })} class="name">Old News</a>
		{#if archive}<span class="mode">Archive</span>{/if}
		<!-- The last successful poll, which answers "is this working". Not a count: the
		     roadmap ruled those out and nothing here reopens it. -->
		<span class="polled">
			<span class="dated">{dated}</span><span class="poll"
				>{polled ? `Updated ${polled}` : 'Not polled yet'}</span
			>
			<span class="sep"></span><a
				href={archive ? links.list(links.NOWHERE) : links.contents()}
				class="linked">{archive ? 'River' : 'Archive'}</a
			>
			<span class="sep"></span><a href="/settings" class="linked">Settings</a>
		</span>
	</div>
	<div class="hair"></div>
	<div class="heavy"></div>
</header>

<style>
	header {
		container-type: inline-size;
		flex: none;
		padding: max(env(safe-area-inset-top), 0.75rem) var(--gutter) 0;
		background: var(--paper);
	}

	.line {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 1rem;
	}

	/* Beside the nameplate rather than replacing it: the archive is a view, not a
	   different paper. */
	.mode {
		flex: none;
		margin-right: auto;
		font-size: 10.5px;
		font-weight: 700;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	.name {
		font-family: var(--display);
		font-size: clamp(25px, 1.1rem + 1.6cqi, 34px);
		font-weight: 900;
		line-height: 1;
		letter-spacing: -0.022em;
	}

	/* The paper's date joins the dateline only where there is room for it, which is a
	   question about this header's own box and not about the window. */
	.dated {
		display: none;
	}

	@container (min-width: 40rem) {
		.dated {
			display: inline;
		}

		.dated::after {
			content: '\00a0\00a0·\00a0\00a0';
		}
	}

	.linked {
		border-bottom: 1px solid var(--underline);
	}

	/* Its own element, not a `::before` on the link: an underline on the anchor draws
	   under everything inside it, separator included, and no rule on the pseudo-element
	   can lift the parent's. `.dated::after` already does it this way. */
	.sep::before {
		content: '\00a0\00a0·\00a0\00a0';
	}

	.polled {
		font-size: 9.5px;
		font-weight: 600;
		letter-spacing: 0.13em;
		text-transform: uppercase;
		color: var(--ink-faint);
		white-space: nowrap;
	}

	/* A hairline, a 2px gap, then a heavy rule. The one piece of newspaper furniture the
	   whole design leans on. */
	.hair {
		margin-top: 9px;
	}

	.heavy {
		height: 3px;
		background: var(--rule);
		margin-top: 2px;
	}
</style>
