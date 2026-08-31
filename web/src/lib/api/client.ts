import { error } from '@sveltejs/kit';
import type { components } from './schema';

export type Entry = components['schemas']['Entry'];
export type River = components['schemas']['River'];
export type Article = components['schemas']['Article'];

// A prefix, not a host. `tailscale serve --set-path=/api` puts Litestar behind it in the
// deployment and the dev proxy does the same, so nothing here knows where the API lives.
const BASE = '/api';

type Fetcher = typeof globalThis.fetch;
type Query = Record<string, string | number | undefined>;

async function get<T>(fetcher: Fetcher, path: string, query: Query = {}): Promise<T> {
	const pairs = Object.entries(query)
		.filter(([, value]) => value !== undefined && value !== '')
		.map(([key, value]) => [key, String(value)]);
	const search = pairs.length ? `?${new URLSearchParams(pairs)}` : '';

	const response = await fetcher(`${BASE}${path}${search}`);
	if (!response.ok) {
		error(response.status, `${path} answered ${response.status}`);
	}
	return (await response.json()) as T;
}

export function river(fetcher: Fetcher, query: Query = {}): Promise<River> {
	return get<River>(fetcher, '/river/', query);
}

export function article(fetcher: Fetcher, id: string): Promise<Article> {
	return get<Article>(fetcher, `/items/${id}/`);
}

export function sections(fetcher: Fetcher): Promise<string[]> {
	return get<string[]>(fetcher, '/sections/');
}

export function markOpened(id: string): Promise<Response> {
	return fetch(`${BASE}/items/${id}/opened/`, { method: 'POST' });
}
