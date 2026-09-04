<script lang="ts">
	import * as links from '#lib/links.ts';

	let {
		sections,
		current,
		archive = false,
	}: { sections: string[]; current: string; archive?: boolean } = $props();

	let sheet = $state<HTMLDialogElement | undefined>();

	const all = $derived(['', ...sections]);

	function href(name: string): string {
		return links.section(name, { section: current, archive });
	}

	function label(name: string): string {
		return name || 'Everything';
	}
</script>

<nav>
	<!-- Scrolls, because at 430px it fits about three names. -->
	<ul class="strip">
		{#each all as name (name)}
			<li><a href={href(name)} class:current={name === current}>{label(name)}</a></li>
		{/each}
	</ul>
	<!-- Pinned outside the scroll behind a rule, so nothing is ever unreachable and the
	     height never changes. -->
	<button class="pin" onclick={() => sheet?.showModal()}>All &#9662;</button>
</nav>
<div class="edge"></div>

<dialog bind:this={sheet} onclick={(event) => event.target === sheet && sheet?.close()}>
	<p class="sheethead">Sections</p>
	<div class="hair"></div>
	<ul class="full">
		{#each all as name (name)}
			<li>
				<a
					href={href(name)}
					class:current={name === current}
					onclick={() => sheet?.close()}
				>
					{label(name)}
				</a>
			</li>
		{/each}
	</ul>
</dialog>

<style>
	nav {
		display: flex;
		align-items: stretch;
		font-size: 10.5px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		background: var(--paper);
	}

	.strip {
		flex-grow: 1;
		min-width: 0;
		display: flex;
		gap: 14px;
		align-items: baseline;
		margin: 0;
		padding: 9px 14px 9px var(--gutter);
		list-style: none;
		white-space: nowrap;
		overflow-x: auto;
		scrollbar-width: none;
	}

	.strip::-webkit-scrollbar {
		display: none;
	}

	.strip a {
		color: var(--ink-faint);
	}

	.strip a.current {
		color: var(--ink);
		font-weight: 700;
	}

	.pin {
		flex-shrink: 0;
		padding: 9px var(--gutter) 9px 14px;
		border-left: 1px solid var(--hair);
		letter-spacing: inherit;
		font-size: inherit;
		text-transform: inherit;
	}

	.edge {
		height: 1px;
		background: var(--rule);
	}

	dialog {
		margin: auto auto 0;
	}

	.full a.current {
		font-weight: 700;
	}
</style>
