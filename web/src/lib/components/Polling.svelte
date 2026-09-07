<script lang="ts">
	import type { Polling } from '#lib/api/client.ts';
	import { stamp } from '#lib/format.ts';

	let { feeds }: { feeds: Polling[] } = $props();

	// A 304 is a healthy poll that happened to carry nothing, and a robots refusal is a
	// rule rather than a fault. Only one of these is the publisher breaking.
	const SAID = {
		ok: 'Answered',
		not_modified: 'Nothing new',
		disallowed: 'Refused by robots',
		failed: 'Failed',
	} as const;

	function said(feed: Polling): string {
		if (feed.gone) return 'Withdrawn';
		if (!feed.outcome) return 'Never polled';
		const words = SAID[feed.outcome as keyof typeof SAID] ?? feed.outcome;
		return feed.status ? `${words} · ${feed.status}` : words;
	}
</script>

{#if feeds.length === 0}
	<p class="none label">Nothing followed yet.</p>
{:else}
	<ul>
		{#each feeds as feed (feed.id)}
			<li class:sick={feed.consecutive_failures > 0 || feed.gone}>
				<div class="what">
					<b>{feed.title || feed.url}</b>
					<span class="said">{said(feed)}</span>
				</div>
				<dl>
					<div>
						<dt>Last</dt>
						<dd>{stamp(feed.last_success_at) || '—'}</dd>
					</div>
					<div>
						<dt>Next</dt>
						<dd>{stamp(feed.next_poll_at)}</dd>
					</div>
					<div>
						<dt>Failures</dt>
						<dd>{feed.consecutive_failures}</dd>
					</div>
				</dl>
				{#if feed.error}<p class="error">{feed.error}</p>{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	li {
		padding: 13px 0;
		border-top: 1px solid var(--hair);
		border-left: 3px solid transparent;
	}

	li:first-child {
		border-top: none;
	}

	/* The bar is on every row so a failing one does not shift the column, and the whole
	   point of the screen is that the broken feeds are at the top wearing it. */
	li.sick {
		padding-left: 10px;
		border-left-color: var(--rule);
	}

	.what {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		align-items: baseline;
		justify-content: space-between;
	}

	.what b {
		flex: 1 1 12rem;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--display);
		font-size: 16px;
		line-height: 1.2;
	}

	.said {
		flex: none;
		font-size: 9.5px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	li.sick .said {
		color: var(--ink);
	}

	dl {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 18px;
		margin: 7px 0 0;
	}

	dl div {
		display: flex;
		gap: 6px;
		align-items: baseline;
	}

	dt,
	dd {
		margin: 0;
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	dt {
		color: var(--ink-faint);
	}

	dd {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	/* The publisher's own words, which is the only place on this screen anything is
	   quoted rather than counted. */
	.error {
		margin: 7px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--ink-soft);
		overflow-wrap: break-word;
	}
</style>
