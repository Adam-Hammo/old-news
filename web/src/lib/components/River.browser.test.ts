import type { Entry, Listing } from '#lib/api/client.ts';
import { finished } from '#lib/finished.ts';
import { NOWHERE, type View } from '#lib/links.ts';
import { opened } from '#lib/opened.ts';
import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import River from './River.svelte';

// Nothing is routing in a component test, so the navigation in flight is stated here.
const nav = vi.hoisted(() => ({ to: null as { params: { id: string } } | null }));
vi.mock('$app/state', () => ({ navigating: nav }));

// The page after the first, so a test can have it answer, refuse, or never come back.
const next = vi.hoisted(() => ({
	answer: null as (() => Promise<unknown>) | null,
	asked: [] as string[],
}));
vi.mock('#lib/api/client.ts', () => ({
	listing: (_fetcher: unknown, _view: unknown, after = '') => {
		next.asked.push(after);
		return next.answer?.() ?? new Promise(() => {});
	},
}));

beforeEach(() => {
	next.answer = null;
	next.asked.length = 0;
	opened.clear();
	finished.clear();
});

function entry(over: Partial<Entry> = {}): Entry {
	const now = new Date().toISOString();
	return {
		id: 'aaaaaaaa-0000-4000-8000-000000000001',
		title: 'A quiet street in Leeds',
		url: 'https://example.com/a',
		outlet: 'The Guardian',
		author: 'Priya Raman',
		published_at: now,
		first_seen_at: now,
		read: false,
		sent: false,
		queued: false,
		snippet: '',
		...over,
	};
}

const page = (entries: Entry[], cursor = ''): Listing => ({
	entries,
	cursor,
	updated: null,
	shelf: '',
});

// What `api.listing` answers with: the list, and a count where anything counted.
const result = (entries: Entry[], cursor = '') => ({ listing: page(entries, cursor), total: null });

// The foot of the river carries a link too, so a test after a row has to name it.
const ROW = { name: /A quiet street/ };

const show = (
	entries: Entry[],
	over: { view?: Partial<View>; selected?: string } = {},
	cursor = '',
) =>
	render(River, {
		page: page(entries, cursor),
		selected: over.selected ?? '',
		view: { ...NOWHERE, ...over.view },
	});

test('a row is a headline and a byline', async () => {
	const screen = await show([entry()]);

	await expect.element(screen.getByText('A quiet street in Leeds')).toBeVisible();
	await expect.element(screen.getByText('The Guardian')).toBeVisible();
	await expect.element(screen.getByText('Priya Raman')).toBeVisible();
});

// A feed in two sections has no correct one to show, so the outlet does that work.
test('no row claims a section', async () => {
	const screen = await show([entry()], { view: { section: 'Technology' } });

	await expect.element(screen.getByRole('link', ROW)).not.toHaveTextContent('Technology');
});

test('the section travels with the link, so coming back lands where you left', async () => {
	const screen = await show([entry({ id: 'abc' })], { view: { section: 'Long form' } });

	await expect
		.element(screen.getByRole('link', ROW))
		.toHaveAttribute('href', '/item/abc?section=Long%20form');
});

test('an opened row is dimmed', async () => {
	const screen = await show([entry({ read: true })]);

	await expect.element(screen.getByRole('link', ROW)).toHaveClass(/\bread\b/);
});

test('the row being read is marked, which is what the second pane is for', async () => {
	const screen = await show([entry({ id: 'abc' })], { selected: 'abc' });

	await expect.element(screen.getByRole('link', ROW)).toHaveClass(/\bselected\b/);
});

// Selecting a row must not move the rows around it, so every row reserves the bar.
test('an unselected row reserves the width the selection marker takes', async () => {
	const screen = await show([entry()]);

	const row = screen.container.querySelector('.row')!;
	expect(getComputedStyle(row).borderLeftWidth).toBe('3px');
});

// The separator is a `::before` on the span, so an author nobody recorded must not get one.
test('an author nobody recorded leaves no stray separator', async () => {
	const screen = await show([entry({ author: '' })]);

	expect(screen.container.querySelectorAll('.by span')).toHaveLength(0);
});

test('an empty river says so rather than showing nothing at all', async () => {
	const screen = await show([]);

	await expect.element(screen.getByText('Nothing here yet.')).toBeVisible();
});

// The masthead's last poll is the only clock on the screen. A date against a row that is
// ordered by something else only reads as an ordering that has gone wrong.
test('a row carries no date', async () => {
	const screen = await show([entry()]);

	expect(screen.container.querySelector('.by')!.textContent).not.toMatch(/\d/);
});

// A third of the authors in the archive are messy strings, some of them whole production
// credits. A row that grows to fit one wrecks the skim the river is for.
test('a byline stays on one line however long the author is', async () => {
	const screen = await show([
		entry({
			author: 'Diane Kraal, Adjunct Senior Research Fellow, Business Law and Taxation, Monash Business School',
		}),
	]);

	const byline = screen.container.querySelector('.by')!;
	expect(getComputedStyle(byline).whiteSpace).toBe('nowrap');
	expect(byline.getBoundingClientRect().height).toBeLessThan(20);
});

test('the outlet is never the part that gets cut', async () => {
	const screen = await show([
		entry({ outlet: 'London Review of Books', author: 'A'.repeat(300) }),
	]);

	expect(screen.container.querySelector('.by b')!.textContent).toBe('London Review of Books');
});

// A tap has to wait for the article's own load, and silence for that long reads as a
// tap that missed.
test('the row being opened is marked while its load is still out', async () => {
	const row = entry();
	nav.to = { params: { id: row.id } };

	const screen = await show([row]);

	expect(screen.container.querySelector('.row')!.classList).toContain('opening');
	nav.to = null;
});

test('with nothing in flight no row is marked', async () => {
	nav.to = null;

	const screen = await show([entry()]);

	expect(screen.container.querySelector('.row')!.classList).not.toContain('opening');
});

// The foot of the list asks for the next page as it comes into view, so nothing about
// carrying on is a thing the reader has to find.
test('the page after the first is asked for by the foot of the list', async () => {
	const screen = await show([entry()], {}, 'page-2');

	await expect.poll(() => next.asked).toEqual(['page-2']);
	expect(screen.container.querySelector('button')).toBeNull();
});

test('the next page is appended under the first', async () => {
	next.answer = () => Promise.resolve(result([entry({ id: 'bbb', title: 'Later that week' })]));

	const screen = await show([entry()], {}, 'page-2');

	await expect.element(screen.getByText('Later that week')).toBeVisible();
	await expect.element(screen.getByText('A quiet street in Leeds')).toBeVisible();
	// That page carried no cursor of its own, so there is nothing left to reach for.
	await expect.poll(() => screen.container.querySelector('.more')).toBeNull();
});

// A river that gives up halfway has taken the rest of the archive with it.
test('a page that would not load can be asked for again', async () => {
	next.answer = () => Promise.reject(new Error('the tailnet went away'));

	const screen = await show([entry()], {}, 'page-2');
	const retry = screen.getByRole('button', { name: /Could not load more/ });
	await expect.element(retry).toBeVisible();

	next.answer = () => Promise.resolve(result([entry({ id: 'bbb', title: 'Later that week' })]));
	await retry.click();

	await expect.element(screen.getByText('Later that week')).toBeVisible();
});

test('a new first page replaces what had been appended to the old one', async () => {
	next.answer = () => Promise.resolve(result([entry({ id: 'bbb', title: 'Later that week' })]));

	const screen = await show([entry()], {}, 'page-2');
	await expect.element(screen.getByText('Later that week')).toBeVisible();

	await screen.rerender({ page: page([entry({ id: 'ccc', title: 'Just this section' })]) });

	await expect.element(screen.getByText('Just this section')).toBeVisible();
	expect(screen.container.querySelectorAll('li')).toHaveLength(1);
});

// The row was opened in this session and the server has not been asked since.
test('a row opened here is dimmed like one the server calls read', async () => {
	const row = entry();
	opened.add(row.id);

	const screen = await show([row]);

	await expect.element(screen.getByRole('link', ROW)).toHaveClass(/\bread\b/);
});

test('a sent row is marked solid and a due one dashed', async () => {
	const screen = await show([
		entry({ id: 'aaaaaaaa-0000-4000-8000-00000000000a', sent: true }),
		entry({ id: 'aaaaaaaa-0000-4000-8000-00000000000b', queued: true }),
	]);

	const marks = screen.container.querySelectorAll('.kindle');
	expect(marks).toHaveLength(2);
	expect(getComputedStyle(marks[0]).borderBottomStyle).toBe('solid');
	expect(getComputedStyle(marks[1]).borderBottomStyle).toBe('dashed');
});

test('a row nothing has claimed carries no mark', async () => {
	const screen = await show([entry()]);

	expect(screen.container.querySelectorAll('.kindle')).toHaveLength(0);
});

test('reading a due row to the bottom drops its mark without a refetch', async () => {
	const due = entry({ queued: true });
	const screen = await show([due]);
	expect(screen.container.querySelectorAll('.kindle')).toHaveLength(1);

	finished.add(due.id);

	await expect.poll(() => screen.container.querySelectorAll('.kindle').length).toBe(0);
});

// The book has already gone out; reading it afterwards cannot unsend it.
test('a sent row keeps its mark', async () => {
	const gone = entry({ sent: true });
	const screen = await show([gone]);

	finished.add(gone.id);

	await expect.poll(() => screen.container.querySelectorAll('.kindle.sent').length).toBe(1);
});

test('the foot of the river is the door to the archive', async () => {
	const screen = await show([entry()], { view: { section: 'Essays' } });

	await expect
		.element(screen.getByRole('link', { name: /archive/i }))
		.toHaveAttribute('href', '/archive');
});

// A shelf has an end, which is the whole reason it is a shelf and not the river.
test('a shelf says where it stops rather than offering another door', async () => {
	const screen = await show([entry()], { view: { feed: 'f1' } });

	await expect.element(screen.getByText('That is the whole shelf.')).toBeVisible();
	expect(screen.container.querySelectorAll('.end a')).toHaveLength(0);
});

test('an empty shelf says so in its own words', async () => {
	const screen = await show([], { view: { month: '2026-06' } });

	await expect.element(screen.getByText('Nothing on this shelf.')).toBeVisible();
});

// Not the end of the list, so not where the door belongs.
test('a page still loading offers no door', async () => {
	const screen = await show([entry()], {}, 'more');

	expect(screen.container.querySelectorAll('.end')).toHaveLength(0);
});

test('the shelf travels with a row link, so coming back stays on the shelf', async () => {
	const screen = await show([entry({ id: 'abc' })], {
		view: { month: '2026-06', tier: 'archive' },
	});

	await expect
		.element(screen.getByRole('link', ROW))
		.toHaveAttribute('href', '/item/abc?month=2026-06&tier=archive');
});

// Only a search row has one, and it is what makes a result recognisable without opening it.
test('a search row carries the fragment that says why it matched', async () => {
	const screen = await show([entry({ snippet: 'the \u0002density\u0003 of it' })], {
		view: { q: 'density' },
	});

	const found = screen.container.querySelector('.found')!;
	expect(found.textContent).toContain('density');
	expect(found.querySelector('b')!.textContent).toBe('density');
});

// A publisher's prose, so markup in it is shown rather than run.
test('markup in a fragment is text', async () => {
	const screen = await show([entry({ snippet: 'a <b>bold</b> claim' })], { view: { q: 'bold' } });

	const found = screen.container.querySelector('.found')!;
	expect(found.querySelector('b')).toBeNull();
	expect(found.textContent).toContain('<b>bold</b>');
});

test('a river row carries no fragment', async () => {
	const screen = await show([entry()]);

	expect(screen.container.querySelector('.found')).toBeNull();
});

test('a search that matched nothing says so in its own words', async () => {
	const screen = await show([], { view: { q: 'wombat' } });

	await expect.element(screen.getByText('Nothing matched.')).toBeVisible();
});
