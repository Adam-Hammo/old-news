import { NOWHERE, type View } from '#lib/links.ts';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Masthead from './Masthead.svelte';

const view = (over: Partial<View> = {}): View => ({ ...NOWHERE, ...over });

// Not a count of anything. The roadmap ruled unread counts out; what a reader actually
// wants to know on arrival is whether the thing is still collecting.
test('the masthead carries the last successful poll', async () => {
	// Built from today rather than written down: `stamp` gives a date once the poll is
	// not today's, so a fixed one turns this into a question about what day it is.
	const polled = new Date();
	polled.setHours(9, 41, 0, 0);
	const screen = await render(Masthead, { updated: polled.toISOString() });

	// Anchored: the masthead answers "is this working", never "how many have you missed".
	expect(screen.container.querySelector('.poll')!.textContent).toMatch(/^Updated \d{2}\.\d{2}$/);
});

test('and says so plainly when nothing has been polled', async () => {
	const screen = await render(Masthead, { updated: null });

	expect(screen.container.querySelector('.poll')!.textContent).toBe('Not polled yet');
});

test('the name goes back to the river, keeping the section you were in', async () => {
	const screen = await render(Masthead, { view: view({ section: 'Long form' }), updated: null });

	await expect
		.element(screen.getByRole('link', { name: 'Old News' }))
		.toHaveAttribute('href', '/?section=Long%20form');
});

// The separator used to be a `::before` inside each link, so the anchor's underline ran
// under the bullet as well as the word.
test('the separator between the controls is not underlined', async () => {
	const screen = await render(Masthead, { updated: null });

	const separators = screen.container.querySelectorAll('.sep');
	expect(separators.length).toBeGreaterThan(0);
	for (const separator of separators) {
		expect(getComputedStyle(separator).borderBottomWidth).toBe('0px');
		expect(getComputedStyle(separator, '::before').borderBottomWidth).toBe('0px');
	}
});

test('but the controls themselves are', async () => {
	const screen = await render(Masthead, { updated: null });

	for (const control of screen.container.querySelectorAll('.linked')) {
		expect(getComputedStyle(control).borderBottomWidth).toBe('1px');
	}
});

test('the archive is reachable without paging to the foot of the river', async () => {
	const screen = await render(Masthead, { view: view({ section: 'Essays' }), updated: null });

	await expect
		.element(screen.getByRole('link', { name: 'Archive' }))
		.toHaveAttribute('href', '/archive');
});

test('and from the contents page the masthead crosses back', async () => {
	const screen = await render(Masthead, { inside: true, updated: null });

	await expect.element(screen.getByRole('link', { name: 'River' })).toHaveAttribute('href', '/');
});

// A shelf is in the archive as much as the contents page is, so it says so too.
test('a shelf is named as the archive without being told', async () => {
	const screen = await render(Masthead, { view: view({ feed: 'f1' }), updated: null });

	expect(screen.container.querySelector('.mode')!.textContent).toBe('Archive');
	await expect.element(screen.getByRole('link', { name: 'River' })).toHaveAttribute('href', '/');
});
