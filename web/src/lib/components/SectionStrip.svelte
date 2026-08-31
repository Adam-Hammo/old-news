<script lang="ts">
	let { sections, current }: { sections: string[]; current: string } = $props();

	let sheet = $state<HTMLDialogElement | undefined>();

	const all = $derived(['', ...sections]);

	function href(name: string): string {
		return name ? `/?section=${encodeURIComponent(name)}` : '/';
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
		width: 100%;
		max-width: 430px;
		padding: 0 0 env(safe-area-inset-bottom);
		color: var(--ink);
		background: var(--paper);
		border: 0;
		border-top: 4px solid var(--rule);
	}

	dialog::backdrop {
		background: var(--scrim);
	}

	.sheethead {
		margin: 0;
		padding: 13px var(--gutter) 9px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.22em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	.hair {
		height: 1px;
		background: var(--rule);
	}

	.full {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.full a {
		display: flex;
		align-items: center;
		height: 56px;
		padding: 0 var(--gutter);
		border-bottom: 1px solid var(--hair);
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.1em;
	}

	.full a.current {
		font-weight: 700;
	}
</style>
