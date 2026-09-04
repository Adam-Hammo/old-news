import { error } from '@sveltejs/kit';
import * as links from '#lib/links.ts';
import type { View } from '#lib/links.ts';
import type { components } from './schema';

export type Entry = components['schemas']['Entry'];
export type Listing = components['schemas']['Listing'];
export type Found = components['schemas']['Found'];
export type Contents = components['schemas']['Contents'];
export type Run = components['schemas']['Run'];
export type Volume = components['schemas']['Volume'];
export type Article = components['schemas']['Article'];
export type Report = components['schemas']['Report'];
export type Following = components['schemas']['Following'];

// A prefix, not a host. `tailscale serve --set-path=/api` puts Litestar behind it in the
// deployment and the dev proxy does the same, so nothing here knows where the API lives.
export const BASE = '/api';

// What the API rewrites a held picture's address to. It is an API path like any other, so
// it needs the prefix — an `<img src="/images/…">` asks the node process serving the page.
const HELD = '/images/';

/** A held picture's address, behind the prefix. Anything else is the publisher's and stays. */
export function held(url: string): string {
	return url.startsWith(HELD) ? `${BASE}${url}` : url;
}

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

/** Months are grouped where the reader is, so the shelf a date lands on is the right one. */
export const ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function contents(fetcher: Fetcher): Promise<Contents> {
	return get<Contents>(fetcher, '/archive/', { zone: ZONE });
}

/** A list, and how much matched where anything counted it. Null is nobody counting. */
export type Result = { listing: Listing; total: number | null };

/** Whichever list the view describes: a slice of the river, a shelf, or a search. */
export async function listing(fetcher: Fetcher, view: View, after = ''): Promise<Result> {
	if (view.q) {
		return get<Found>(fetcher, '/archive/search/', { q: view.q, after });
	}
	const { feed, month, tier } = view;
	const listing = links.archived(view)
		? await get<Listing>(fetcher, '/archive/items/', { feed, month, tier, after, zone: ZONE })
		: await get<Listing>(fetcher, '/river/', { section: view.section, after });
	// The river has no total by design, and a shelf's is already on the contents page.
	return { listing, total: null };
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

export type Filing = components['schemas']['Filing'];

/** The whole filing every time: a partial one cannot say "never expires". */
export function file(id: string, filing: Filing): Promise<string> {
	return send(`/subscriptions/${id}/`, 'PATCH', filing);
}

export function unfollow(id: string): Promise<string> {
	return send(`/subscriptions/${id}/`, 'DELETE');
}

/** Fire and forget: nothing reads the answer, and a dead tailnet must not reject unhandled. */
export function markOpened(id: string): void {
	void fetch(`${BASE}/items/${id}/opened/`, { method: 'POST' }).catch(() => {});
}

/** Reaching the bottom, which is what keeps an article out of the next issue. */
export function markFinished(id: string): void {
	void fetch(`${BASE}/items/${id}/finished/`, { method: 'POST' }).catch(() => {});
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
