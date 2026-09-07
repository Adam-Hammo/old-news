import type { Shape } from '#lib/api/client.ts';
import { EVERYTHING, type View } from '#lib/links.ts';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Facets from './Facets.svelte';

function shape(over: Partial<Shape> = {}): Shape {
	return {
		publications: [
			{ name: 'Pluralistic (Cory Doctorow)', items: 7 },
			{ name: 'Kagi News', items: 2 },
		],
		months: [{ name: '2026-08', items: 9 }],
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
		.element(screen.getByRole('link', { name: /Pluralistic/ }))
		.toHaveAttribute('href', '/archive?q=from%3A%22Pluralistic%20(Cory%20Doctorow)%22');
});

test('a month line adds the pair of dates the grammar spells one with', async () => {
	const screen = await show();

	await expect
		.element(screen.getByRole('link', { name: /August 2026/ }))
		.toHaveAttribute('href', '/archive?q=after%3A2026-08%20before%3A2026-09');
});

// Narrowing, not replacing: the rail is a way of editing the query rather than starting one.
test('a line adds to whatever is already typed', async () => {
	const screen = await show({ q: 'enshittification' });

	await expect
		.element(screen.getByRole('link', { name: /Never opened/ }))
		.toHaveAttribute('href', '/archive?q=enshittification%20is%3Aunread');
});

// `includes` marked the Reuters row for a query naming ReutersHealth.
test('a longer name that starts the same does not mark the shorter one', async () => {
	const screen = await show(
		{ q: 'from:PluralisticWeekly' },
		{
			publications: [{ name: 'Pluralistic', items: 3 }],
		},
	);

	await expect
		.element(screen.getByRole('link', { name: /Pluralistic/ }))
		.not.toHaveClass(/\bon\b/);
});

test('and a quoted name is still recognised whole', async () => {
	const screen = await show(
		{ q: 'from:"Kagi News"' },
		{
			publications: [{ name: 'Kagi News', items: 3 }],
		},
	);

	await expect.element(screen.getByRole('link', { name: /Kagi News/ })).toHaveClass(/\bon\b/);
});

test('a term already in the query is marked as one you are standing in', async () => {
	const screen = await show({ q: 'is:unread' });

	await expect.element(screen.getByRole('link', { name: /Never opened/ })).toHaveClass(/\bon\b/);
	await expect.element(screen.getByRole('link', { name: /Opened/ })).not.toHaveClass(/\bon\b/);
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
