import { expect, test } from 'vitest';
import { load } from './+layout.ts';

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

// SvelteKit reruns a load on every navigation once it has read the path, which refetched
// the river under each article opened and dropped every page scrolled past on the way back.
test('the layout never reads the path', async () => {
	const url = new Proxy(new URL('http://localhost/item/abc?section=World'), {
		get(target, key) {
			if (key === 'pathname' || key === 'href') throw new Error(`read url.${key}`);
			const value = Reflect.get(target, key);
			return typeof value === 'function' ? value.bind(target) : value;
		},
	});
	const fetch: typeof globalThis.fetch = (input) =>
		Promise.resolve(
			json(
				String(input).includes('/sections/')
					? []
					: { entries: [], cursor: '', updated: null },
			),
		);

	await expect(load({ fetch, url, params: { id: 'abc' } } as never)).resolves.toMatchObject({
		archive: false,
		view: { section: 'World' },
	});
});
