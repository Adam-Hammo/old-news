import { expect, test } from 'vitest';
import { NOWHERE } from '#lib/links.ts';
import { TIMEOUT, article, listing } from './client.ts';

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

// A navigation waits on its load, so without a deadline a dead signal is a tap that
// never does anything. The abort itself is covered by the case below.
test('every request carries a deadline', async () => {
	let carried: AbortSignal | null | undefined;
	const ok: typeof fetch = (_url, init) => {
		carried = init?.signal;
		return Promise.resolve(json({ entries: [], cursor: '', updated: null }));
	};

	await listing(ok, NOWHERE);

	expect(carried).toBeInstanceOf(AbortSignal);
	expect(carried!.aborted).toBe(false);
	expect(TIMEOUT).toBeGreaterThan(0);
});

test('a tailnet that is not there is a 504, not an unhandled error', async () => {
	const dead: typeof fetch = () => Promise.reject(new TypeError('Load failed'));

	await expect(article(dead, 'aaaa')).rejects.toMatchObject({ status: 504 });
});

// The API's own status still has to survive: a 404 is a missing article, not a dead link.
test('a status the API did answer with is kept', async () => {
	const missing: typeof fetch = () => Promise.resolve(new Response('', { status: 404 }));

	await expect(article(missing, 'aaaa')).rejects.toMatchObject({ status: 404 });
});

test('a request that answers in time is not touched', async () => {
	const ok: typeof fetch = () =>
		Promise.resolve(json({ entries: [], cursor: '', updated: null }));

	await expect(listing(ok, NOWHERE)).resolves.toMatchObject({ listing: { entries: [] } });
});
