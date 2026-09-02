import { error } from '@sveltejs/kit';
import type { components } from './schema';

export type Entry = components['schemas']['Entry'];
export type River = components['schemas']['River'];
export type Article = components['schemas']['Article'];
export type Report = components['schemas']['Report'];
export type Following = components['schemas']['Following'];

// A prefix, not a host. `tailscale serve --set-path=/api` puts Litestar behind it in the
// deployment and the dev proxy does the same, so nothing here knows where the API lives.
const BASE = '/api';

// A navigation waits on its load, so a request that never answers is a tap that never
// does anything. Better to give up and say so than to hang on a phone's dead signal.
export const TIMEOUT = 10_000;

type Fetcher = typeof globalThis.fetch;
type Query = Record<string, string | number | undefined>;

async function get<T>(fetcher: Fetcher, path: string, query: Query = {}): Promise<T> {
	const pairs = Object.entries(query)
		.filter(([, value]) => value !== undefined && value !== '')
		.map(([key, value]) => [key, String(value)]);
	const search = pairs.length ? `?${new URLSearchParams(pairs)}` : '';

	let response: Response;
	try {
		response = await fetcher(`${BASE}${path}${search}`, {
			signal: AbortSignal.timeout(TIMEOUT),
		});
	} catch {
		// A thrown fetch is the tailnet, not the API: no status, so one is chosen here
		// rather than left to surface as an unhandled 500.
		error(504, `${path} did not answer`);
	}
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

export function following(fetcher: Fetcher): Promise<Following[]> {
	return get<Following[]>(fetcher, '/subscriptions/');
}

/** The API's own words on the way out: it knows why, and the screen only has to say it. */
async function send(path: string, method: string, body?: unknown): Promise<string> {
	let response: Response;
	try {
		response = await fetch(`${BASE}${path}`, {
			method,
			signal: AbortSignal.timeout(TIMEOUT),
			...(body === undefined
				? {}
				: { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
		});
	} catch {
		return 'The tailnet did not answer.';
	}
	if (response.ok) return '';
	return (
		((await response.json().catch(() => ({}))) as { detail?: string }).detail ?? 'That failed.'
	);
}

export function follow(url: string, category: string): Promise<string> {
	return send('/subscriptions/', 'POST', { url, category });
}

export function file(id: string, category: string): Promise<string> {
	return send(`/subscriptions/${id}/`, 'PATCH', { category });
}

export function unfollow(id: string): Promise<string> {
	return send(`/subscriptions/${id}/`, 'DELETE');
}

/** Fire and forget: nothing reads the answer, and a dead tailnet must not reject unhandled. */
export function markOpened(id: string): void {
	void fetch(`${BASE}/items/${id}/opened/`, { method: 'POST' }).catch(() => {});
}

/** Fire and forget, and `keepalive` so a report outlives the page that made it. A failed
 *  report must not become a second failure. */
export function sendReport(report: Report): void {
	void fetch(`${BASE}/client-reports/`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(report),
		keepalive: true,
	}).catch(() => {});
}
