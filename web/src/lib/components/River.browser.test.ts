import type { Entry, River as Page } from '#lib/api/client.ts';
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
	river: (_fetcher: unknown, query: { after?: string }) => {
		next.asked.push(query.after ?? '');
		return next.answer?.() ?? new Promise(() => {});
	},
}));

beforeEach(() => {
	next.answer = null;
	next.asked.length = 0;
	opened.clear();
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
		...over,
	};
}

const page = (entries: Entry[], cursor = ''): Page => ({ entries, cursor, updated: null });

const show = (entries: Entry[], over: { section?: string; selected?: string } = {}, cursor = '') =>
	render(River, { page: page(entries, cursor), section: '', selected: '', ...over });

test('a row is a headline and a byline', async () => {
	const screen = await show([entry()]);

	await expect.element(screen.getByText('A quiet street in Leeds')).toBeVisible();
	await expect.element(screen.getByText('The Guardian')).toBeVisible();
	await expect.element(screen.getByText('Priya Raman')).toBeVisible();
});

// A feed in two sections has no correct one to show, so the outlet does that work.
test('no row claims a section', async () => {
	const screen = await show([entry()], { section: 'Technology' });

	await expect.element(screen.getByRole('link')).not.toHaveTextContent('Technology');
});

test('the section travels with the link, so coming back lands where you left', async () => {
	const screen = await show([entry({ id: 'abc' })], { section: 'Long form' });

	await expect
		.element(screen.getByRole('link'))
		.toHaveAttribute('href', '/item/abc?section=Long%20form');
});

test('an opened row is dimmed', async () => {
	const screen = await show([entry({ read: true })]);

	await expect.element(screen.getByRole('link')).toHaveClass(/\bread\b/);
});

test('the row being read is marked, which is what the second pane is for', async () => {
	const screen = await show([entry({ id: 'abc' })], { selected: 'abc' });

	await expect.element(screen.getByRole('link')).toHaveClass(/\bselected\b/);
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
	next.answer = () => Promise.resolve(page([entry({ id: 'bbb', title: 'Later that week' })]));

	const screen = await show([entry()], {}, 'page-2');

	await expect.element(screen.getByText('Later that week')).toBeVisible();
	await expect.element(screen.getByText('A quiet street in Leeds')).toBeVisible();
	// That page carried no cursor of its own, so there is nothing left to reach for.
	await expect.poll(() => screen.container.querySelector('.note')).toBeNull();
});

// A river that gives up halfway has taken the rest of the archive with it.
test('a page that would not load can be asked for again', async () => {
	next.answer = () => Promise.reject(new Error('the tailnet went away'));

	const screen = await show([entry()], {}, 'page-2');
	const retry = screen.getByRole('button', { name: /Could not load more/ });
	await expect.element(retry).toBeVisible();

	next.answer = () => Promise.resolve(page([entry({ id: 'bbb', title: 'Later that week' })]));
	await retry.click();

	await expect.element(screen.getByText('Later that week')).toBeVisible();
});

test('a new first page replaces what had been appended to the old one', async () => {
	next.answer = () => Promise.resolve(page([entry({ id: 'bbb', title: 'Later that week' })]));

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

	await expect.element(screen.getByRole('link')).toHaveClass(/\bread\b/);
});
