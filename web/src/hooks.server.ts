import type { Handle } from '@sveltejs/kit/hooks';

// In the deployment `tailscale serve --set-path=/api` puts Litestar on this origin and
// this hook never fires, because OLD_NEWS_API is unset there. It exists so the compose
// stack has the same two paths on one origin without standing a proxy container up to
// play the part of the tailnet.
const upstream = process.env.OLD_NEWS_API;

const PREFIX = '/api';
const BODYLESS = new Set(['GET', 'HEAD']);

export const handle: Handle = async ({ event, resolve }) => {
	if (!upstream || !event.url.pathname.startsWith(`${PREFIX}/`)) return resolve(event);

	// The prefix is stripped, which is what `--set-path` does and what lets Litestar stay
	// ignorant of where it is mounted.
	const target = new URL(event.url.pathname.slice(PREFIX.length) + event.url.search, upstream);
	const method = event.request.method;

	return fetch(target, {
		method,
		headers: event.request.headers,
		body: BODYLESS.has(method) ? undefined : await event.request.arrayBuffer(),
	});
};
