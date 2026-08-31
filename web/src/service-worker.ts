import { version } from '$app/env';
import { self as worker } from '$app/service-worker';

// One job, and one page. No reading works offline and nothing else is kept.
const CACHE = `offline-${version}`;
const OFFLINE = '/offline.html';

worker.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then((cache) => cache.add(new Request(OFFLINE, { cache: 'reload' })))
			.then(() => worker.skipWaiting()),
	);
});

worker.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((names) =>
				Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))),
			)
			.then(() => worker.clients.claim()),
	);
});

worker.addEventListener('fetch', (event) => {
	if (event.request.mode !== 'navigate') return;

	event.respondWith(
		fetch(event.request)
			// The host answered, so the tailnet is up and the app is not. A thrown fetch is
			// the other way round, and the two want different advice.
			.then((response) => (response.status >= 500 ? offline('app') : response))
			.catch(() => offline('tailnet')),
	);
});

async function offline(reason: 'app' | 'tailnet'): Promise<Response> {
	const page = await (await caches.open(CACHE)).match(OFFLINE);
	const html = (await page?.text()) ?? '';

	return new Response(html.replace('%reason%', reason), {
		status: 503,
		headers: { 'content-type': 'text/html; charset=utf-8' },
	});
}
