import * as api from '#lib/api/client.ts';
import { NOWHERE, type View } from '#lib/links.ts';
import type { LayoutLoad } from './$types';

// The API is same-origin from the browser and nowhere else. Rendering on the server would
// mean the node process calling back through `tailscale serve` to reach Litestar, so the
// shell is served and the data is fetched from where the prefix actually resolves.
export const ssr = false;

// The contents page is the whole screen. Every other route has a list beside it.
const CONTENTS = '/archive';

// The list is loaded here rather than by its own route: on a wide screen the article
// renders beside it, so the list cannot belong to the page the article replaces.
export const load: LayoutLoad = async ({ fetch, url }) => {
	const view: View = {
		section: url.searchParams.get('section') ?? '',
		feed: url.searchParams.get('feed') ?? '',
		month: url.searchParams.get('month') ?? '',
		tier: url.searchParams.get('tier') ?? '',
		q: url.searchParams.get('q') ?? '',
	};
	// When, so the reading UI knows how old what it is showing has got.
	const at = Date.now();

	if (url.pathname === CONTENTS) {
		const contents = await api.contents(fetch);
		return { view: NOWHERE, sections: [], list: null, total: null, contents, at };
	}
	const [sections, result] = await Promise.all([api.sections(fetch), api.listing(fetch, view)]);
	return { view, sections, list: result.listing, total: result.total, contents: null, at };
};
