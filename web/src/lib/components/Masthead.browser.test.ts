import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Masthead from './Masthead.svelte';

// Not a count of anything. The roadmap ruled unread counts out; what a reader actually
// wants to know on arrival is whether the thing is still collecting.
test('the masthead carries the last successful poll', async () => {
	const screen = await render(Masthead, { updated: '2026-08-31T09:41:00Z' });

	// Anchored: the masthead answers "is this working", never "how many have you missed".
	expect(screen.container.querySelector('.poll')!.textContent).toMatch(/^Updated \d{2}\.\d{2}$/);
});

test('and says so plainly when nothing has been polled', async () => {
	const screen = await render(Masthead, { updated: null });

	expect(screen.container.querySelector('.poll')!.textContent).toBe('Not polled yet');
});

test('the name goes back to the river, keeping the section you were in', async () => {
	const screen = await render(Masthead, { section: 'Long form', updated: null });

	await expect
		.element(screen.getByRole('link', { name: 'Old News' }))
		.toHaveAttribute('href', '/?section=Long%20form');
});
