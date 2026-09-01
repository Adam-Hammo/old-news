import * as api from '#lib/api/client.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => ({
	feeds: await api.following(fetch),
});
