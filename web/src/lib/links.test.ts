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

// A quote cannot be spelt inside a quoted run, and it would close the one around the name.
test('a quote in a name comes out rather than closing the run early', () => {
	expect(links.from('Kagi News "Weekly"')).toBe('from:"Kagi News Weekly"');
});

test('a month is the pair of dates the grammar spells one with', () => {
	expect(links.within('2026-06')).toBe('after:2026-06 before:2026-07');
});

// A date facet counts years until the query is inside one, so a year has to be clickable.
test('a year is a pair of dates too', () => {
	expect(links.within('2026')).toBe('after:2026 before:2027');
});

test('december rolls into the next year', () => {
	expect(links.within('2025-12')).toBe('after:2025-12 before:2026-01');
});

// Clicking the rail narrows what is already there rather than replacing it.
test('a term is added to whatever is already typed', () => {
	expect(links.toggled(held({ q: 'density' }), 'is:unread')).toBe(
		'/archive?q=density%20is%3Aunread',
	);
});

test('and is the whole query when nothing was typed', () => {
	expect(links.toggled(links.EVERYTHING, 'is:unread')).toBe('/archive?q=is%3Aunread');
});

// A filter you cannot take off is one you have to retype the query to escape.
test('a term already on comes off again', () => {
	expect(links.toggled(held({ q: 'density is:unread' }), 'is:unread')).toBe('/archive?q=density');
});

test('and taking the last one off is everything held again', () => {
	expect(links.toggled(held({ q: 'is:unread' }), 'is:unread')).toBe('/archive');
});

test('a quoted term comes off whole', () => {
	expect(links.toggled(held({ q: 'from:"Kagi News" density' }), 'from:"Kagi News"')).toBe(
		'/archive?q=density',
	);
});

test('what the query carries is matched whole, never as a substring', () => {
	expect(links.carries(held({ q: 'from:Reuters' }), 'from:Reuters')).toBe(true);
	expect(links.carries(held({ q: 'from:ReutersHealth' }), 'from:Reuters')).toBe(false);
	expect(links.carries(held({ q: 'from:"Kagi News"' }), 'from:"Kagi News"')).toBe(true);
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

// The rail labels its periods `2026-06` and `2026`; a reader is owed words.
test('a month reads as a month', () => {
	expect(links.volume('2026-06')).toBe('June 2026');
});

test('and a year is already its own word', () => {
	expect(links.volume('2026')).toBe('2026');
});

test('a label nothing can be made of is shown as it came', () => {
	expect(links.volume('not-a-month')).toBe('not-a-month');
});

// Once the query is inside a year, the rail's own 2026 row is gone — it lists that year's
// months instead — so nothing in the rail can take the year back off.
test('what is applied reads as words, each with the query that drops it', () => {
	expect(links.applied(held({ q: 'after:2026 before:2027' }))).toEqual([
		{ label: '2026', without: '' },
	]);
});

test('a month pair reads as the month', () => {
	expect(links.applied(held({ q: 'after:2026-08 before:2026-09' }))[0].label).toBe('August 2026');
});

// `before:` is exclusive, so a period is named for what it takes in, never for the bound.
test('half a range still reads as one, and reads as what it includes', () => {
	expect(links.applied(held({ q: 'after:2026-08' }))[0].label).toBe('August 2026 on');
	expect(links.applied(held({ q: 'before:2026-09' }))[0].label).toBe('up to August 2026');
});

test('and a range across periods names the last one it takes in', () => {
	expect(links.applied(held({ q: 'after:2026-06 before:2026-08' }))[0].label).toBe(
		'June 2026 to July 2026',
	);
	expect(links.applied(held({ q: 'after:2026 before:2028' }))[0].label).toBe('2026 to 2027');
});

test('a publication reads as its name and an exclusion says so', () => {
	expect(links.applied(held({ q: 'from:"Kagi News"' }))[0].label).toBe('Kagi News');
	expect(links.applied(held({ q: '-from:guardian' }))[0].label).toBe('not guardian');
});

// A publication and an author can be the same word, and two chips wearing one name says
// nothing about either — and used to take the whole screen down on a duplicate key.
test('an author says so, so it cannot be mistaken for a publication', () => {
	const both = links.applied(held({ q: 'from:guardian by:guardian' }));

	expect(both.map((one) => one.label)).toEqual(['guardian', 'by guardian']);
	expect(new Set(both.map((one) => one.without)).size).toBe(2);
});

test('and the same term twice is one term', () => {
	expect(links.applied(held({ q: 'from:guardian from:guardian' }))).toEqual([
		{ label: 'guardian', without: '' },
	]);
});

test('a state reads as the words the rail uses for it', () => {
	expect(links.applied(held({ q: 'is:unread' }))[0].label).toBe('Never opened');
});

// Half a phrase is not a search anybody typed.
test('the words are one thing and come off together', () => {
	const [words] = links.applied(held({ q: 'housing density' }));

	expect(words.label).toBe('\u201chousing density\u201d');
	expect(words.without).toBe('');
});

test('and everything at once comes off one piece at a time', () => {
	const view = held({ q: 'density from:pluralistic after:2026 before:2027 is:unread' });

	expect(links.applied(view).map((one) => one.label)).toEqual([
		'2026',
		'pluralistic',
		'Never opened',
		'\u201cdensity\u201d',
	]);
	expect(links.applied(view)[0].without).toBe('density from:pluralistic is:unread');
});

test('nothing asked is nothing applied', () => {
	expect(links.applied(links.EVERYTHING)).toEqual([]);
});

// A period is two terms, so comparing it against single tokens never matched — the row
// stayed clickable-on forever and a second pair stacked up that the parser overruled.
test('a period counts as carried only when both its bounds are', () => {
	expect(links.carries(held({ q: 'after:2026 before:2027' }), links.within('2026'))).toBe(true);
	expect(links.carries(held({ q: 'after:2026' }), links.within('2026'))).toBe(false);
});

test('and it comes off in one click', () => {
	const view = held({ q: 'density after:2026 before:2027' });

	expect(links.toggled(view, links.within('2026'))).toBe('/archive?q=density');
});

// `after:2026 before:2027 after:2026-08 before:2026-09` is what stacking looked like.
test('picking another period replaces the one already there', () => {
	const view = held({ q: 'density after:2026 before:2027' });

	expect(links.toggled(view, links.within('2026-08'))).toBe(
		'/archive?q=density%20after%3A2026-08%20before%3A2026-09',
	);
});

test('but a second publication is an OR and stacks', () => {
	const view = held({ q: 'from:abc' });

	expect(links.toggled(view, 'from:sbs')).toBe('/archive?q=from%3Aabc%20from%3Asbs');
});

// The quotes are the grammar's, not the reader's: they were showing up inside the chip.
test('a phrase reads without the quotes that made it one', () => {
	expect(links.applied(held({ q: '"housing density"' }))[0].label).toBe(
		'\u201chousing density\u201d',
	);
});
