import { SvelteSet } from 'svelte/reactivity';

/** Read to the bottom in this session, so a row loses its marker without refetching. */
export const finished = new SvelteSet<string>();
