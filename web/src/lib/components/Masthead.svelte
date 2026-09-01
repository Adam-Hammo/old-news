<script lang="ts">
	import { stamp, today } from '#lib/format.ts';

	let { section = '', updated = null }: { section?: string; updated?: string | null } = $props();

	const home = $derived(section ? `/?section=${encodeURIComponent(section)}` : '/');
	const polled = $derived(stamp(updated));
	const dated = today();
</script>

<header>
	<div class="line">
		<a href={home} class="name">Old News</a>
		<!-- The last successful poll, which answers "is this working". Not a count: the
		     roadmap ruled those out and nothing here reopens it. -->
		<span class="polled">
			<span class="dated">{dated}</span><span class="poll"
				>{polled ? `Updated ${polled}` : 'Not polled yet'}</span
			>
			<a href="/settings" class="settings">Settings</a>
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

	.settings {
		border-bottom: 1px solid var(--underline);
	}

	.settings::before {
		content: '\00a0\00a0·\00a0\00a0';
		border-bottom: 0;
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
		height: 1px;
		background: var(--rule);
		margin-top: 9px;
	}

	.heavy {
		height: 3px;
		background: var(--rule);
		margin-top: 2px;
	}
</style>
