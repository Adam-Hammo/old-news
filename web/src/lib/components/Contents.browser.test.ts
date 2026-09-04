import type { Contents, Run, Volume } from '#lib/api/client.ts';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ContentsView from './Contents.svelte';

function run(over: Partial<Run> = {}): Run {
	return {
		feed_id: 'f1',
		title: 'Construction Physics',
		url: 'https://constructionphysics.substack.com/feed',
		tier: 'kindle',
		dropped: false,
		items: 42,
		latest: new Date().toISOString(),
		...over,
	};
}

function held(over: Partial<Contents> = {}): Contents {
	const months: Volume[] = [{ month: '2026-06', items: 42 }];
	return { items: 42, months, feeds: [run()], updated: null, ...over };
}

const show = (over: Partial<Contents> = {}) => render(ContentsView, { held: held(over) });

test('the contents says how much is held rather than making you scroll to find out', async () => {
	const screen = await show({ items: 4760 });

	await expect.element(screen.getByText(/4,760 pieces/)).toBeVisible();
});

test('a publication is a shelf you can open', async () => {
	const screen = await show();

	await expect
		.element(screen.getByRole('link', { name: /Construction Physics/ }))
		.toHaveAttribute('href', '/?feed=f1');
});

test('a month is a shelf you can open, in words rather than in a date format', async () => {
	const screen = await show();

	await expect
		.element(screen.getByRole('link', { name: /June 2026/ }))
		.toHaveAttribute('href', '/?month=2026-06');
});

// The wire is over half the archive and none of the reason to walk it, so it is the one
// shelf that arrives shut.
test('the wire is folded away and everything else is open', async () => {
	const screen = await show({
		feeds: [
			run({ feed_id: 'w1', title: 'The Guardian', tier: 'wire' }),
			run({ feed_id: 'k1', title: 'Quanta', tier: 'kindle' }),
		],
	});

	const folded = screen.container.querySelectorAll('details');
	expect(folded).toHaveLength(1);
	expect(folded[0].open).toBe(false);
	expect(folded[0].textContent).toContain('The Guardian');
	await expect.element(screen.getByRole('link', { name: /Quanta/ })).toBeVisible();
});

test('a dropped feed is still on the shelf, filed as no longer followed', async () => {
	const screen = await show({
		feeds: [run({ feed_id: 'g1', title: 'Gone Away', dropped: true })],
	});

	const folded = screen.container.querySelector('details')!;
	expect(folded.textContent).toContain('No longer followed');
	expect(folded.textContent).toContain('Gone Away');
});

// The tier is what decides whether a back catalogue is worth walking, so it is the order.
test('the shelves are ordered by how much trouble the publication is worth', async () => {
	const screen = await show({
		feeds: [
			run({ feed_id: 'a1', title: 'Nautilus', tier: 'archive' }),
			run({ feed_id: 'k1', title: 'Quanta', tier: 'kindle' }),
		],
	});

	const headings = [...screen.container.querySelectorAll('h3')].map((h) => h.textContent);
	expect(headings).toEqual(['Sent as a book', 'Kept in full']);
});

test('an archive with nothing in it says so', async () => {
	const screen = await show({ items: 0, months: [], feeds: [] });

	await expect.element(screen.getByText('Nothing held yet.')).toBeVisible();
});

// One item in one month must not draw an empty bar, and the fullest must not overflow it.
test('a month is drawn against the fullest one', async () => {
	const screen = await show({
		months: [
			{ month: '2026-06', items: 100 },
			{ month: '2026-05', items: 25 },
		],
	});

	const bars = [...screen.container.querySelectorAll('.bar')] as HTMLElement[];
	expect(bars.map((bar) => bar.style.getPropertyValue('--fill'))).toEqual(['100%', '25%']);
});
