import * as api from '#lib/api/client.ts';
import { EVERYTHING, NOWHERE, type View } from '#lib/links.ts';
import type { LayoutLoad } from './$types';

// The API is same-origin from the browser and nowhere else. Rendering on the server would
// mean the node process calling back through `tailscale serve` to reach Litestar, so the
// shell is served and the data is fetched from where the prefix actually resolves.
export const ssr = false;

// Both lists load here rather than in their own route: on a wide screen the article
// renders over or beside one, so the list cannot belong to the page the article replaces.
// The param rather than the path: reading `url.pathname` reruns this on every navigation,
// opening an article included.
export const load: LayoutLoad = async ({ fetch, url, params }) => {
	const archive = Boolean(params.archive);
	const view: View = archive
		? { ...EVERYTHING, q: url.searchParams.get('q') ?? '' }
		: { ...NOWHERE, section: url.searchParams.get('section') ?? '' };
	// When, so the reading UI knows how old what it is showing has got.
	const at = Date.now();

	if (archive) {
		const [result, shape] = await Promise.all([
			api.listing(fetch, view),
			api.facets(fetch, view),
		]);
		return {
			archive,
			view,
			sections: [],
			list: result.listing,
			total: result.total,
			shape,
			at,
		};
	}
	const [sections, result] = await Promise.all([api.sections(fetch), api.listing(fetch, view)]);
	return {
		archive,
		view,
		sections,
		list: result.listing,
		total: result.total,
		shape: null,
		at,
	};
};
