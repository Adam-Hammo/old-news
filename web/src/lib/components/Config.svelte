<script lang="ts">
	import type { Section } from '#lib/api/client.ts';

	let { config }: { config: Section[] } = $props();
</script>

{#each config as section (section.name)}
	<h3>{section.name}</h3>
	<dl>
		{#each section.settings as setting (setting.name)}
			<div>
				<dt>{setting.name.replaceAll('_', ' ')}</dt>
				<dd>{setting.value}</dd>
			</div>
		{/each}
	</dl>
{/each}

<style>
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

	h3:first-child {
		margin-top: 0;
	}

	dl {
		margin: 0;
	}

	dl div {
		display: flex;
		gap: 12px;
		align-items: baseline;
		justify-content: space-between;
		padding: 8px 0;
		border-top: 1px solid var(--hair);
	}

	dl div:first-child {
		border-top: none;
	}

	dt,
	dd {
		margin: 0;
		min-width: 0;
	}

	dt {
		font-size: 10.5px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	/* The value is the answer, so it is the half that keeps its room and the half that
	   is allowed to break: a user agent string is one word as far as the browser knows. */
	dd {
		flex: 0 1 auto;
		text-align: right;
		font-size: 13px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		overflow-wrap: break-word;
	}
</style>
