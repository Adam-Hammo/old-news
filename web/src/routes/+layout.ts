import * as api from '#lib/api/client.ts';
import type { LayoutLoad } from './$types';

// The API is same-origin from the browser and nowhere else. Rendering on the server would
// mean the node process calling back through `tailscale serve` to reach Litestar, so the
// shell is served and the data is fetched from where the prefix actually resolves.
export const ssr = false;

// The river is loaded here rather than by its own route: on a wide screen the article
// renders beside it, so the list cannot belong to the page the article replaces.
export const load: LayoutLoad = async ({ fetch, url }) => {
	const section = url.searchParams.get('section') ?? '';
	const [sections, river] = await Promise.all([
		api.sections(fetch),
		api.river(fetch, { section }),
	]);
	// When, so the reading UI knows how old what it is showing has got.
	return { sections, river, section, at: Date.now() };
};
