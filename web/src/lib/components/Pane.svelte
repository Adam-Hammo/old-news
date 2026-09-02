<script lang="ts">
	import type { Snippet } from 'svelte';

	let { back, children }: { back: string; children: Snippet } = $props();
</script>

<div class="pane">
	<div class="top measured">
		<a href={back} class="up">&larr;&nbsp;&nbsp;River</a>
		<div class="hair"></div>
	</div>

	<!-- Children carry `.measured` themselves: the article's bar spans the pane, not the column. -->
	{@render children()}
</div>

<style>
	.pane {
		display: flex;
		flex-direction: column;
		min-height: 100%;
		background: var(--paper-read);
	}

	.top {
		flex: none;
		padding: max(env(safe-area-inset-top), 0.75rem) var(--gutter) 0;
	}

	.up {
		display: inline-block;
		padding-bottom: 9px;
		font-size: 10.5px;
		font-weight: 600;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}
</style>
