import type { Entry, River as Page } from '#lib/api/client.ts';
import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import River from './River.svelte';

// Nothing is routing in a component test, so the navigation in flight is stated here.
const nav = vi.hoisted(() => ({ to: null as { params: { id: string } } | null }));
vi.mock('$app/state', () => ({ navigating: nav }));

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

test('a row is a headline and a byline', async () => {
	const screen = await render(River, { page: page([entry()]), section: '', selected: '' });

	await expect.element(screen.getByText('A quiet street in Leeds')).toBeVisible();
	await expect.element(screen.getByText('The Guardian')).toBeVisible();
	await expect.element(screen.getByText('Priya Raman')).toBeVisible();
});

// A feed in two sections has no correct one to show, so the outlet does that work.
test('no row claims a section', async () => {
	const screen = await render(River, {
		page: page([entry()]),
		section: 'Technology',
		selected: '',
	});

	await expect.element(screen.getByRole('link')).not.toHaveTextContent('Technology');
});

test('the section travels with the link, so coming back lands where you left', async () => {
	const screen = await render(River, {
		page: page([entry({ id: 'abc' })]),
		section: 'Long form',
		selected: '',
	});

	await expect
		.element(screen.getByRole('link'))
		.toHaveAttribute('href', '/item/abc?section=Long%20form');
});

test('an opened row is dimmed', async () => {
	const screen = await render(River, {
		page: page([entry({ read: true })]),
		section: '',
		selected: '',
	});

	await expect.element(screen.getByRole('link')).toHaveClass(/\bread\b/);
});

test('the row being read is marked, which is what the second pane is for', async () => {
	const screen = await render(River, {
		page: page([entry({ id: 'abc' })]),
		section: '',
		selected: 'abc',
	});

	await expect.element(screen.getByRole('link')).toHaveClass(/\bselected\b/);
});

// Selecting a row must not move the rows around it, so every row reserves the bar.
test('an unselected row reserves the width the selection marker takes', async () => {
	const screen = await render(River, { page: page([entry()]), section: '', selected: '' });

	const row = screen.container.querySelector('.row')!;
	expect(getComputedStyle(row).borderLeftWidth).toBe('3px');
});

// The separator is a `::before` on the span, so an author nobody recorded must not get one.
test('an author nobody recorded leaves no stray separator', async () => {
	const screen = await render(River, {
		page: page([entry({ author: '' })]),
		section: '',
		selected: '',
	});

	expect(screen.container.querySelectorAll('.by span')).toHaveLength(0);
});

test('an empty river says so rather than showing nothing at all', async () => {
	const screen = await render(River, { page: page([]), section: '', selected: '' });

	await expect.element(screen.getByText('Nothing here yet.')).toBeVisible();
});

// The masthead's last poll is the only clock on the screen. A date against a row that is
// ordered by something else only reads as an ordering that has gone wrong.
test('a row carries no date', async () => {
	const screen = await render(River, { page: page([entry()]), section: '', selected: '' });

	expect(screen.container.querySelector('.by')!.textContent).not.toMatch(/\d/);
});

// A third of the authors in the archive are messy strings, some of them whole production
// credits. A row that grows to fit one wrecks the skim the river is for.
test('a byline stays on one line however long the author is', async () => {
	const screen = await render(River, {
		page: page([
			entry({
				author: 'Diane Kraal, Adjunct Senior Research Fellow, Business Law and Taxation, Monash Business School',
			}),
		]),
		section: '',
		selected: '',
	});

	const byline = screen.container.querySelector('.by')!;
	expect(getComputedStyle(byline).whiteSpace).toBe('nowrap');
	expect(byline.getBoundingClientRect().height).toBeLessThan(20);
});

test('the outlet is never the part that gets cut', async () => {
	const screen = await render(River, {
		page: page([entry({ outlet: 'London Review of Books', author: 'A'.repeat(300) })]),
		section: '',
		selected: '',
	});

	expect(screen.container.querySelector('.by b')!.textContent).toBe('London Review of Books');
});

// A tap has to wait for the article's own load, and silence for that long reads as a
// tap that missed.
test('the row being opened is marked while its load is still out', async () => {
	const row = entry();
	nav.to = { params: { id: row.id } };

	const screen = await render(River, { page: page([row]), section: '', selected: '' });

	expect(screen.container.querySelector('.row')!.classList).toContain('opening');
	nav.to = null;
});

test('with nothing in flight no row is marked', async () => {
	nav.to = null;

	const screen = await render(River, { page: page([entry()]), section: '', selected: '' });

	expect(screen.container.querySelector('.row')!.classList).not.toContain('opening');
});
