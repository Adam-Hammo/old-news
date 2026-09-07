import { expect, test } from 'vitest';
import * as links from './links.ts';

const view = (over: Partial<links.View> = {}): links.View => ({ ...links.NOWHERE, ...over });
const held = (over: Partial<links.View> = {}): links.View => ({ ...links.EVERYTHING, ...over });

test('the whole river needs no query at all', () => {
	expect(links.list(links.NOWHERE)).toBe('/');
});

// The path is what says which screen, so the archive with nothing typed is still its own.
test('the archive with nothing asked of it is everything it holds', () => {
	expect(links.archive()).toBe('/archive');
	expect(links.archived(links.EVERYTHING)).toBe(true);
	expect(links.archived(links.NOWHERE)).toBe(false);
});

// `URLSearchParams` spells a space `+`, and the rest of the app spells it `%20`. Two
// spellings of one view is two URLs for one screen.
test('a space in a section is spelt the way the rest of the app spells it', () => {
	expect(links.section('Long form')).toBe('/?section=Long%20form');
});

test('a query is encoded whole, operators and all', () => {
	expect(links.list(held({ q: 'density from:pluralistic' }))).toBe(
		'/archive?q=density%20from%3Apluralistic',
	);
});

// The archive has no sections and the river has no query, so neither carries the other's.
test('neither screen carries the other screen key', () => {
	expect(links.list(held({ q: 'density', section: 'Essays' }))).toBe('/archive?q=density');
	expect(links.list(view({ section: 'Essays', q: 'density' }))).toBe('/?section=Essays');
});

test('a publication is asked for by name', () => {
	expect(links.from('Pluralistic')).toBe('from:Pluralistic');
});

// A bare name with a space in it would split into a name and a stray word.
test('a name with a space in it is quoted so it survives the split', () => {
	expect(links.from('Kagi News')).toBe('from:"Kagi News"');
});

test('a month is the pair of dates the grammar spells one with', () => {
	expect(links.within('2026-06')).toBe('after:2026-06 before:2026-07');
});

test('december rolls into the next year', () => {
	expect(links.within('2025-12')).toBe('after:2025-12 before:2026-01');
});

// Clicking the rail narrows what is already there rather than replacing it.
test('a term is added to whatever is already typed', () => {
	expect(links.and(held({ q: 'density' }), 'is:unread')).toBe('/archive?q=density%20is%3Aunread');
});

test('and is the whole query when nothing was typed', () => {
	expect(links.and(links.EVERYTHING, 'is:unread')).toBe('/archive?q=is%3Aunread');
});

test('a search is a view like any other, spaces spelt the same way', () => {
	expect(links.search('housing density')).toBe('/archive?q=housing%20density');
});

// An article keeps the screen it was opened from: the archive covers, the river sits beside.
test('an article opened from the archive stays in the archive', () => {
	expect(links.item('abc', held({ q: 'density' }))).toBe('/archive/item/abc?q=density');
	expect(links.item('abc', links.EVERYTHING)).toBe('/archive/item/abc');
});

test('and one opened from the river stays in the river', () => {
	expect(links.item('abc', view({ section: 'Essays' }))).toBe('/item/abc?section=Essays');
});

// The rail labels its months `2026-06`; a reader is owed words.
test('a month reads as a month', () => {
	expect(links.volume('2026-06')).toBe('June 2026');
});

test('a label nothing can be made of is shown as it came', () => {
	expect(links.volume('not-a-month')).toBe('not-a-month');
});
