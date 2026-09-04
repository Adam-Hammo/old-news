<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import * as api from '#lib/api/client.ts';
	import type { Following } from '#lib/api/client.ts';

	let { feeds, sections }: { feeds: Following[]; sections: string[] } = $props();

	// How much trouble a feed is worth. The levels nest, so kindle takes what archive
	// does: every picture held, and the book on top.
	const TIERS = [
		{ value: 'wire', label: 'Wire' },
		{ value: 'archive', label: 'Archive' },
		{ value: 'kindle', label: 'Kindle' },
	];

	// A handful of named lengths rather than a number: the difference between five days
	// and six is not an opinion anybody has. Null is the feed nothing ages out of.
	const WINDOWS = [
		{ value: '21600', label: '6 hours' },
		{ value: '86400', label: '1 day' },
		{ value: '259200', label: '3 days' },
		{ value: '604800', label: '1 week' },
		{ value: '1209600', label: '2 weeks' },
		{ value: '3628800', label: '6 weeks' },
		{ value: '15552000', label: '6 months' },
		{ value: '', label: 'Never' },
	];

	let url = $state('');
	let category = $state('');
	let busy = $state(false);
	let said = $state('');
	// The feed whose Drop has been pressed once. One press used to be the whole gesture,
	// which is a poll history gone on a mistap.
	let arming = $state('');

	// Every section already in use, plus any a feed carries that the river has not got to.
	const known = $derived(
		[...new Set([...sections, ...feeds.map((f) => f.category)])].filter(Boolean).sort(),
	);

	// Filed the way the river slices it, so a long list shows where a section begins and
	// ends. Unfiled last: it is the absence of a section rather than one more of them.
	const filed = $derived(
		Object.entries(Object.groupBy(feeds, (feed) => feed.category)).sort(([a], [b]) =>
			a === '' ? 1 : b === '' ? -1 : a.localeCompare(b),
		),
	);

	async function act(work: () => Promise<string>) {
		if (busy) return;
		busy = true;
		said = await work();
		if (!said) await invalidateAll();
		busy = false;
	}

	/** The whole filing, with one field replaced. A partial PATCH cannot say "never". */
	function filing(feed: Following, over: Partial<api.Filing> = {}): api.Filing {
		return {
			category: feed.category,
			tier: feed.tier,
			expires_after_seconds: feed.expires_after_seconds,
			...over,
		};
	}

	function drop(id: string) {
		if (arming !== id) {
			arming = id;
			return;
		}
		arming = '';
		void act(() => api.unfollow(id));
	}

	const add = () =>
		act(async () => {
			const failed = await api.follow(url.trim(), category.trim());
			if (!failed) url = '';
			return failed;
		});
</script>

<section>
	<h2>Feeds</h2>
	<p class="say">
		Paste a feed, or the address of a site that has one &mdash; it will be found. Dropping a
		feed stops the polling and keeps everything already read; it takes two presses. The tier is
		how much trouble a feed is worth: the wire keeps a lead image, archive holds every picture,
		and kindle does that and sends the weekly book.
	</p>

	<form
		onsubmit={(event) => {
			event.preventDefault();
			void add();
		}}
	>
		<input
			bind:value={url}
			type="url"
			required
			placeholder="https://example.com"
			aria-label="Feed or site address"
		/>
		<div class="row">
			<input
				bind:value={category}
				list="sections"
				placeholder="Section (optional)"
				aria-label="Section"
			/>
			<button disabled={busy} type="submit">Follow</button>
		</div>
	</form>
	{#if said}<p class="said" role="alert">{said}</p>{/if}

	<datalist id="sections">
		{#each known as name (name)}<option value={name}></option>{/each}
	</datalist>

	{#if feeds.length === 0}
		<p class="none label">Nothing followed yet.</p>
	{:else}
		{#each filed as [name, group] (name)}
			<h3>{name || 'Unfiled'}</h3>
			<ul>
				{#each group ?? [] as feed (feed.id)}
					<li>
						<div class="what">
							<b>{feed.title || feed.url}</b>
							<a
								href={feed.site_url || feed.url}
								target="_blank"
								rel="noreferrer noopener"
							>
								{feed.url}
							</a>
						</div>
						<div class="row">
							<input
								value={feed.category}
								list="sections"
								placeholder="Unfiled"
								aria-label="Section for {feed.title || feed.url}"
								onchange={(event) =>
									act(() =>
										api.file(
											feed.id,
											filing(feed, {
												category: event.currentTarget.value.trim(),
											}),
										),
									)}
							/>
							<button
								disabled={busy}
								class:arming={arming === feed.id}
								onclick={() => drop(feed.id)}
								onblur={() => arming === feed.id && (arming = '')}
								aria-label={arming === feed.id
									? `Confirm dropping ${feed.title || feed.url}`
									: `Drop ${feed.title || feed.url}`}
								>{arming === feed.id ? 'Confirm' : 'Drop'}</button
							>
						</div>
						<div class="row settings">
							<label>
								<span class="what-for">Tier</span>
								<select
									value={feed.tier}
									aria-label="Tier for {feed.title || feed.url}"
									onchange={(event) =>
										act(() =>
											api.file(
												feed.id,
												filing(feed, { tier: event.currentTarget.value }),
											),
										)}
								>
									{#each TIERS as tier (tier.value)}
										<option value={tier.value}>{tier.label}</option>
									{/each}
								</select>
							</label>
							<label>
								<span class="what-for">Ages out after</span>
								<select
									value={String(feed.expires_after_seconds ?? '')}
									aria-label="Window for {feed.title || feed.url}"
									onchange={(event) =>
										act(() =>
											api.file(
												feed.id,
												filing(feed, {
													expires_after_seconds:
														Number(event.currentTarget.value) || null,
												}),
											),
										)}
								>
									{#each WINDOWS as span (span.value)}
										<option value={span.value}>{span.label}</option>
									{/each}
								</select>
							</label>
						</div>
					</li>
				{/each}
			</ul>
		{/each}
	{/if}
</section>

<style>
	h2 {
		margin: 0;
		padding-top: 18px;
		font-family: var(--display);
		font-size: 22px;
		font-weight: 700;
		letter-spacing: -0.015em;
	}

	.say {
		margin: 8px 0 18px;
		font-size: 15px;
		line-height: 1.5;
		color: var(--ink-soft);
		text-wrap: pretty;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-bottom: 4px;
	}

	.row {
		display: flex;
		gap: 8px;
	}

	input {
		flex: 1;
		min-width: 0;
		padding: 9px 10px;
		font: inherit;
		font-size: 15px;
		color: var(--ink);
		background: var(--paper);
		border: 1px solid var(--hair);
		border-radius: 0;
	}

	input:focus-visible {
		outline: 2px solid var(--ink);
		outline-offset: -2px;
	}

	button {
		flex: none;
		padding: 0 16px;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		border: 1px solid var(--rule);
	}

	/* Armed, and inverted so it is plain that the next press is the one that does it. Wide
	   enough for the longer word either way, so arming one does not move the row. */
	li button {
		min-width: 6.25rem;
	}

	button.arming {
		color: var(--paper);
		background: var(--ink);
	}

	button:disabled {
		color: var(--ink-faint);
		border-color: var(--hair);
		cursor: default;
	}

	.said {
		margin: 10px 0 0;
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.06em;
		color: var(--ink);
	}

	.none {
		padding: 1.4rem 0;
	}

	h3 {
		margin: 26px 0 0;
		padding-bottom: 7px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.2em;
		text-transform: uppercase;
		color: var(--ink-faint);
		border-bottom: 1px solid var(--rule);
	}

	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	/* The section's own rule already closes the gap above the first row. */
	li:first-child {
		border-top: none;
	}

	li {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		justify-content: space-between;
		padding: 13px 0;
		border-top: 1px solid var(--hair);
	}

	.what {
		flex: 1 1 14rem;
		min-width: 0;
	}

	.what b {
		display: block;
		font-family: var(--display);
		font-size: 16px;
		line-height: 1.2;
	}

	/* The address is how you tell two feeds from one publisher apart, so it is not decoration. */
	.what a {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		padding-top: 3px;
		font-size: 11.5px;
		color: var(--ink-faint);
	}

	li .row {
		flex: 0 1 20rem;
	}

	/* Their own line: on a phone the section box and the Drop button already fill one. */
	li .settings {
		flex: 1 1 100%;
	}

	label {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.what-for {
		font-size: 9.5px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	select {
		width: 100%;
		padding: 8px 10px;
		font: inherit;
		font-size: 14px;
		color: var(--ink);
		background: var(--paper);
		border: 1px solid var(--hair);
		border-radius: 0;
	}

	select:focus-visible {
		outline: 2px solid var(--ink);
		outline-offset: -2px;
	}
</style>
