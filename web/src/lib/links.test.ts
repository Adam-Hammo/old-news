import { expect, test } from 'vitest';
import * as links from './links.ts';

const view = (over: Partial<links.View> = {}): links.View => ({ ...links.NOWHERE, ...over });

test('the whole river needs no query at all', () => {
	expect(links.list(links.NOWHERE)).toBe('/');
});

// `URLSearchParams` spells a space `+`, and the rest of the app spells it `%20`. Two
// spellings of one view is two URLs for one screen.
test('a space in a section is spelt the way the rest of the app spells it', () => {
	expect(links.section('Long form')).toBe('/?section=Long%20form');
});

// A URL carrying both would claim a section the archive does not have.
test('a query drops the section, because the archive has none', () => {
	expect(links.list(view({ section: 'Essays', q: 'density' }))).toBe('/?q=density');
});

test('a query is encoded whole, operators and all', () => {
	expect(links.list(view({ q: 'density from:pluralistic' }))).toBe(
		'/?q=density%20from%3Apluralistic',
	);
});

test('a publication is asked for by name', () => {
	expect(links.publication('Pluralistic')).toBe('/?q=from%3APluralistic');
});

// A bare name with a space in it would split into a name and a stray word.
test('a name with a space in it is quoted so it survives the split', () => {
	expect(links.publication('Kagi News')).toBe('/?q=from%3A%22Kagi%20News%22');
});

test('a month is the pair of dates the grammar spells one with', () => {
	expect(links.month('2026-06')).toBe('/?q=after%3A2026-06%20before%3A2026-07');
});

test('december rolls into the next year', () => {
	expect(links.month('2025-12')).toBe('/?q=after%3A2025-12%20before%3A2026-01');
});

test('the river is a query of nothing', () => {
	expect(links.archived(links.NOWHERE)).toBe(false);
	expect(links.archived(view({ section: 'Essays' }))).toBe(false);
	expect(links.archived(view({ q: 'density' }))).toBe(true);
});

test('a search is a view like any other, spaces spelt the same way', () => {
	expect(links.search('housing density')).toBe('/?q=housing%20density');
});

test('a query travels with an article, so coming back lands on the results', () => {
	expect(links.item('abc', view({ q: 'density' }))).toBe('/item/abc?q=density');
});

// The archive labels its months `2026-06`; a reader is owed words.
test('a month reads as a month', () => {
	expect(links.volume('2026-06')).toBe('June 2026');
});

test('a label nothing can be made of is shown as it came', () => {
	expect(links.volume('not-a-month')).toBe('not-a-month');
});
