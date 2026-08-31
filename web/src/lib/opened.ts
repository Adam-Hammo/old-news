import { SvelteSet } from 'svelte/reactivity';

/** Opened in this session, so a row dims without refetching the page it sits on. */
export const opened = new SvelteSet<string>();
