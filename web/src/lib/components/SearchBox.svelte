<script lang="ts">
	import { goto } from '$app/navigation';
	import * as links from '#lib/links.ts';

	let { terms = '' }: { terms?: string } = $props();

	// Writable, so typing overrides it and a search arrived at from somewhere else still
	// lands in the field: this sits in the same slot either way and nothing remounts it.
	let asked = $derived(terms);
</script>

<form
	role="search"
	onsubmit={(event) => {
		event.preventDefault();
		const wanted = asked.trim();
		if (wanted) void goto(links.search(wanted));
	}}
>
	<input
		bind:value={asked}
		type="search"
		placeholder="Search everything held"
		aria-label="Search the archive"
	/>
	<button type="submit">Search</button>
</form>

<style>
	form {
		display: flex;
		gap: 8px;
		margin: 0 0 6px;
	}

	input {
		flex: 1;
		min-width: 0;
		padding: 10px 12px;
		font: inherit;
		font-size: 16px;
		color: var(--ink);
		background: var(--paper);
		border: 1px solid var(--rule);
		border-radius: 0;
		/* Safari draws its own, and it sits badly against a square field. */
		appearance: none;
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
</style>
