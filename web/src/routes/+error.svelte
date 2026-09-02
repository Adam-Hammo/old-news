<script lang="ts">
	import { page } from '$app/state';

	// 504 is this client's own word for "the request never answered", which on a phone is
	// the usual way this page gets reached.
	const stalled = $derived(page.status === 504);
</script>

<div class="pane measured">
	<p class="kicker">{stalled ? 'No answer' : `Error ${page.status}`}</p>
	<h1>{stalled ? 'That did not load.' : 'Something went wrong.'}</h1>
	<p class="say">
		{stalled
			? 'The tailnet answered slowly or not at all. Nothing is lost — try it again.'
			: page.error?.message}
	</p>
	<a href="/">&larr;&nbsp; Back to the river</a>
</div>

<style>
	.pane {
		padding: 2.5rem var(--gutter);
	}

	.kicker {
		margin: 0 0 10px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.2em;
		text-transform: uppercase;
		color: var(--ink-faint);
	}

	h1 {
		margin: 0;
		font-family: var(--display);
		font-size: clamp(26px, 1rem + 2cqi, 34px);
		font-weight: 700;
		line-height: 1.06;
		letter-spacing: -0.02em;
	}

	.say {
		margin: 12px 0 1.8rem;
		font-size: 17px;
		line-height: 1.5;
		color: var(--ink-soft);
		text-wrap: pretty;
	}

	a {
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		border-bottom: 1px solid var(--underline);
	}
</style>
