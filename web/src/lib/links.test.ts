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

test('a shelf drops the section, because the archive does not have sections', () => {
	expect(links.list(view({ section: 'Essays', feed: 'f1' }))).toBe('/?feed=f1');
});

test('a shelf can be a publication within a month', () => {
	expect(links.list(view({ feed: 'f1', month: '2026-06' }))).toBe('/?feed=f1&month=2026-06');
});

test('a month can be asked for without the wire', () => {
	expect(links.month('2026-06', 'archive')).toBe('/?month=2026-06&tier=archive');
});

test('and the sift is a link back to the same shelf either way', () => {
	const sifted = view({ month: '2026-06', tier: 'archive' });

	expect(links.wire(sifted, true)).toBe('/?month=2026-06');
	expect(links.wire(view({ month: '2026-06' }), false)).toBe('/?month=2026-06&tier=archive');
});

test('a shelf travels with an article, so coming back lands on it', () => {
	expect(links.item('abc', view({ month: '2026-06' }))).toBe('/item/abc?month=2026-06');
});

test('the river is a shelf of nothing', () => {
	expect(links.archived(links.NOWHERE)).toBe(false);
	expect(links.archived(view({ section: 'Essays' }))).toBe(false);
	expect(links.archived(view({ feed: 'f1' }))).toBe(true);
	expect(links.archived(view({ month: '2026-06' }))).toBe(true);
	expect(links.archived(view({ q: 'density' }))).toBe(true);
});

test('a search is a view like any other, spaces spelt the same way', () => {
	expect(links.search('housing density')).toBe('/?q=housing%20density');
});

test('a search travels with an article, so coming back lands on the results', () => {
	expect(links.item('abc', view({ q: 'density' }))).toBe('/item/abc?q=density');
});

// The archive labels its shelves `2026-06`; a reader is owed words.
test('a month reads as a month', () => {
	expect(links.volume('2026-06')).toBe('June 2026');
});

test('a label nothing can be made of is shown as it came', () => {
	expect(links.volume('not-a-month')).toBe('not-a-month');
});
