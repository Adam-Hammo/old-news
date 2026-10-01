<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import * as api from '#lib/api/client.ts';
	import type { Blocking, Following } from '#lib/api/client.ts';

	let { filters, feeds }: { filters: Blocking[]; feeds: Following[] } = $props();

	const DIMENSIONS = [
		{ value: 'title_phrase', label: 'Title has' },
		{ value: 'url_pattern', label: 'Address has' },
	];

	let dimension = $state('title_phrase');
	let pattern = $state('');
	let feedId = $state('');
	let note = $state('');
	let busy = $state(false);
	let said = $state('');
	// The filter whose Remove has been pressed once, so a mistap does not unhide a feed's
	// live blogs.
	let arming = $state('');

	const named = (value: string) => DIMENSIONS.find((d) => d.value === value)?.label ?? value;

	async function act(work: () => Promise<string>) {
		if (busy) return;
		busy = true;
		said = await work();
		if (!said) await invalidateAll();
		busy = false;
	}

	function remove(id: string) {
		if (arming !== id) {
			arming = id;
			return;
		}
		arming = '';
		void act(() => api.unblock(id));
	}

	const add = () =>
		act(async () => {
			const failed = await api.block({
				dimension,
				pattern: pattern.trim(),
				feed_id: feedId || null,
				note: note.trim(),
			});
			if (!failed) {
				pattern = '';
				note = '';
			}
			return failed;
		});
</script>

<section>
	<h2>Filters</h2>
	<p class="what-for">Hidden from the river and Kindle, and never fetched in full.</p>
	<form
		onsubmit={(event) => {
			event.preventDefault();
			void add();
		}}
	>
		<div class="row">
			<select bind:value={dimension} aria-label="Match on">
				{#each DIMENSIONS as option (option.value)}
					<option value={option.value}>{option.label}</option>
				{/each}
			</select>
			<input bind:value={pattern} required placeholder="live:" aria-label="Pattern" />
		</div>
		<div class="row">
			<select bind:value={feedId} aria-label="Feed">
				<option value="">Every feed</option>
				{#each feeds as feed (feed.id)}
					<option value={feed.id}>{feed.title || feed.url}</option>
				{/each}
			</select>
		</div>
		<div class="row">
			<input bind:value={note} placeholder="Why (optional)" aria-label="Note" />
			<button disabled={busy} type="submit">Block</button>
		</div>
	</form>
	{#if said}<p class="said" role="alert">{said}</p>{/if}

	{#if filters.length === 0}
		<p class="none label">Nothing filtered.</p>
	{:else}
		<ul>
			{#each filters as filter (filter.id)}
				<li>
					<div class="what">
						<b>{filter.pattern}</b>
						<span class="what-for"
							>{named(filter.dimension)} · {filter.feed || 'Every feed'}</span
						>
						{#if filter.note}<span class="note">{filter.note}</span>{/if}
					</div>
					<button
						disabled={busy}
						class:arming={arming === filter.id}
						onclick={() => remove(filter.id)}
						onblur={() => arming === filter.id && (arming = '')}
						aria-label={arming === filter.id
							? `Confirm removing ${filter.pattern}`
							: `Remove ${filter.pattern}`}
						>{arming === filter.id ? 'Confirm' : 'Remove'}</button
					>
				</li>
			{/each}
		</ul>
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

	form {
		margin-top: 18px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-bottom: 4px;
	}

	.row {
		display: flex;
		gap: 8px;
	}

	input,
	select {
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

	.row select:first-child:not(:only-child) {
		flex: none;
	}

	input:focus-visible,
	select:focus-visible {
		outline: 2px solid var(--ink);
		outline-offset: -2px;
	}

	button {
		flex: none;
		min-width: 6.25rem;
		padding: 0 16px;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		border: 1px solid var(--rule);
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

	li button {
		padding: 9px 16px;
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

	.what-for {
		font-size: 9.5px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	h2 + .what-for {
		margin: 6px 0 0;
	}

	ul {
		margin: 22px 0 0;
		padding: 0;
		list-style: none;
		border-top: 1px solid var(--rule);
	}

	li {
		display: flex;
		gap: 10px;
		align-items: center;
		justify-content: space-between;
		padding: 13px 0;
		border-top: 1px solid var(--hair);
	}

	li:first-child {
		border-top: none;
	}

	.what {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.what b {
		overflow-wrap: anywhere;
		font-family: var(--display);
		font-size: 16px;
		line-height: 1.2;
	}

	.note {
		font-size: 12px;
		color: var(--ink-faint);
	}
</style>
