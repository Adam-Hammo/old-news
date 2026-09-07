<script lang="ts">
	import type { Publisher } from '#lib/api/client.ts';
	import { stamp } from '#lib/format.ts';

	let { hosts }: { hosts: Publisher[] } = $props();

	const counted = new Intl.NumberFormat();

	/** What robots.txt asked for, in the words it asked in. Nothing asked is not zero. */
	function delay(host: Publisher): string {
		if (host.crawl_delay_seconds === null) return 'None asked';
		return `${host.crawl_delay_seconds}s`;
	}

	function robots(host: Publisher): string {
		if (!host.robots_fetched_at) return 'Not fetched';
		// 0 is a host that could not be reached, which is not an HTTP status at all.
		return host.robots_status ? String(host.robots_status) : 'No answer';
	}
</script>

{#if hosts.length === 0}
	<p class="none label">Nothing followed yet.</p>
{:else}
	<ul>
		{#each hosts as host (host.name)}
			<li class:sick={host.capture_failures > 0}>
				<div class="what">
					<b>{host.name}</b>
					<span class="tally"
						>{counted.format(host.feeds)}
						{host.feeds === 1 ? 'feed' : 'feeds'}</span
					>
				</div>
				<dl>
					<div>
						<dt>Crawl delay</dt>
						<dd>{delay(host)}</dd>
					</div>
					<div>
						<dt>robots.txt</dt>
						<dd>{robots(host)}</dd>
					</div>
					<div>
						<dt>Read</dt>
						<dd>{stamp(host.robots_fetched_at) || '—'}</dd>
					</div>
					{#if host.requires_www}
						<div>
							<dt>Needs</dt>
							<dd>www.</dd>
						</div>
					{/if}
					{#if host.capture_failures > 0}
						<div>
							<dt>Capture failures</dt>
							<dd>{host.capture_failures}</dd>
						</div>
					{/if}
				</dl>
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

	li.sick {
		padding-left: 10px;
		border-left-color: var(--rule);
	}

	.what {
		display: flex;
		gap: 12px;
		align-items: baseline;
		justify-content: space-between;
	}

	.what b {
		flex: 0 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--display);
		font-size: 16px;
		line-height: 1.2;
	}

	.tally {
		flex: none;
		font-size: 9.5px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--ink-faint);
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
</style>
