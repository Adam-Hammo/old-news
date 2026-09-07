import * as api from '#lib/api/client.ts';
import { tabbed } from '#lib/tabs.ts';
import type { PageLoad } from './$types';

// Only the page on screen. Opening Settings to change one feed's tier must not run every
// query the screen can ask.
export const load: PageLoad = async ({ fetch, url }) => {
	const tab = tabbed(url.searchParams.get('tab'));
	return {
		tab,
		feeds: tab === 'feeds' ? await api.following(fetch) : [],
		polling: tab === 'polling' ? await api.polling(fetch) : [],
		publishers: tab === 'publishers' ? await api.publishers(fetch) : [],
		config: tab === 'config' ? await api.configured(fetch) : [],
	};
};
