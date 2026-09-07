import type { Shape } from '#lib/api/client.ts';
import { EVERYTHING, type View } from '#lib/links.ts';
import { page } from 'vitest/browser';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Facets from './Facets.svelte';

function shape(over: Partial<Shape> = {}): Shape {
	return {
		publications: [
			{ name: 'Pluralistic (Cory Doctorow)', items: 7 },
			{ name: 'Kagi News', items: 2 },
		],
		months: [{ name: '2026', items: 9 }],
		states: [
			{ name: 'unread', items: 11 },
			{ name: 'read', items: 1 },
			{ name: 'finished', items: 0 },
		],
		updated: null,
		...over,
	};
}

const show = (over: Partial<View> = {}, held: Partial<Shape> = {}) =>
	render(Facets, { shape: shape(held), view: { ...EVERYTHING, ...over } });

test('a publication line adds the term that would narrow to it', async () => {
	const screen = await show();

	await expect
		.element(screen.getByRole('link', { name: /Narrow to Pluralistic/ }))
		.toHaveAttribute('href', '/archive?q=from%3A%22Pluralistic%20(Cory%20Doctorow)%22');
});

test('a year line adds the pair of dates the grammar spells one with', async () => {
	const screen = await show();

	await expect
		.element(screen.getByRole('link', { name: /Narrow to 2026/ }))
		.toHaveAttribute('href', '/archive?q=after%3A2026%20before%3A2027');
});

// The count is what this line reaches on its own, which stays worth reading once it is on.
test('a line already on keeps its count and gains the way off', async () => {
	const screen = await show({ q: 'is:unread' });

	const on = screen.container.querySelector('a.on')!;
	expect(on.querySelector('span')!.textContent).toBe('11');
	expect(on.querySelector('em')!.textContent).toBe('×');
});

// Which is a thing every one of these lists ought to say about itself.
test('a heading says how many values the dimension has', async () => {
	const screen = await show();

	const headings = [...screen.container.querySelectorAll('h2')];
	expect(headings.map((h) => h.querySelector('i')!.textContent)).toEqual(['1', '2', '2']);
});

// Narrowing, not replacing: the rail is a way of editing the query rather than starting one.
test('a line adds to whatever is already typed', async () => {
	const screen = await show({ q: 'enshittification' });

	await expect
		.element(screen.getByRole('link', { name: /Narrow to Never opened/ }))
		.toHaveAttribute('href', '/archive?q=enshittification%20is%3Aunread');
});

// It used to re-add the term it was already showing, so there was no way back off a
// filter but retyping the query.
test('a line already on takes itself off again', async () => {
	const screen = await show({ q: 'density is:unread' });

	await expect
		.element(screen.getByRole('link', { name: /Stop narrowing to Never opened/ }))
		.toHaveAttribute('href', '/archive?q=density');
});

test('and taking the last one off is everything held again', async () => {
	const screen = await show({ q: 'is:unread' });

	await expect
		.element(screen.getByRole('link', { name: /Stop narrowing/ }))
		.toHaveAttribute('href', '/archive');
});

test('a term already in the query is marked as one you are standing in', async () => {
	const screen = await show({ q: 'is:unread' });

	await expect.element(screen.getByRole('link', { name: /Never opened/ })).toHaveClass(/\bon\b/);
	await expect
		.element(screen.getByRole('link', { name: /Narrow to Opened/ }))
		.not.toHaveClass(/\bon\b/);
});

// `includes` marked the Reuters row for a query naming ReutersHealth.
test('a longer name that starts the same does not mark the shorter one', async () => {
	const screen = await show(
		{ q: 'from:PluralisticWeekly' },
		{ publications: [{ name: 'Pluralistic', items: 3 }] },
	);

	await expect
		.element(screen.getByRole('link', { name: /Pluralistic/ }))
		.not.toHaveClass(/\bon\b/);
});

test('and a quoted name is still recognised whole', async () => {
	const screen = await show(
		{ q: 'from:"Kagi News"' },
		{ publications: [{ name: 'Kagi News', items: 3 }] },
	);

	await expect.element(screen.getByRole('link', { name: /Kagi News/ })).toHaveClass(/\bon\b/);
});

// A line reading nought is not a choice, it is a dead end with a number on it.
test('a value nothing landed in is not offered', async () => {
	const screen = await show();

	expect(screen.container.textContent).not.toContain('Read to the end');
});

test('and a whole dimension nothing landed in loses its heading too', async () => {
	const screen = await show({}, { months: [] });

	expect(screen.container.textContent).not.toContain('When');
});

// Forty-one publications used to take the whole column and push the third heading off
// the bottom, so no list gets more than a share of the screen.
test('every group keeps its heading and scrolls its own list', async () => {
	// The rail only exists above 62rem; below it these are one horizontal strip.
	await page.viewport(1280, 800);
	const months = Array.from({ length: 50 }, (_, at) => ({
		name: `20${(75 - at).toString().slice(-2)}-01`,
		items: 50 - at,
	}));
	const screen = await show({}, { months });
	const container = screen.container as HTMLElement;

	const headings = [...container.querySelectorAll('h2')];
	const labels = headings.map((heading) => heading.textContent!.trim().split(/\s+/)[0]);
	expect(labels).toEqual(['When', 'Publication', 'You']);
	// Every list capped, so the three of them plus their headings fit one screen.
	const lists = [...container.querySelectorAll('ul')];
	for (const list of lists) {
		expect(list.getBoundingClientRect().height).toBeLessThanOrEqual(window.innerHeight * 0.31);
	}
	expect(lists[0].scrollHeight).toBeGreaterThan(lists[0].clientHeight);
});

// The strip runs in the rail's order, so each group has to keep its name or there is no
// telling where one ends and the next starts.
test('on a phone the groups keep their order and their names', async () => {
	await page.viewport(430, 800);
	const screen = await show();

	const container = screen.container as HTMLElement;
	const headings = [...container.querySelectorAll('h2')];
	expect(headings.map((h) => h.textContent!.trim().split(/\s+/)[0])).toEqual([
		'When',
		'Publication',
		'You',
	]);
	for (const heading of headings) {
		expect(getComputedStyle(heading).display).not.toBe('none');
	}
	// A row each, stacked in that order: one row for all three put `You` five thousand
	// pixels along, behind every publication there is.
	const sections = [...container.querySelectorAll('section')].map((s) =>
		s.getBoundingClientRect(),
	);
	expect(sections[0].top).toBeLessThan(sections[1].top);
	expect(sections[1].top).toBeLessThan(sections[2].top);
	// Every one of them starts at the same margin, so none is off to the side.
	expect(new Set(sections.map((s) => Math.round(s.left))).size).toBe(1);
});
