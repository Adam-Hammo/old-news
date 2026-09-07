import { NOWHERE, type View } from '#lib/links.ts';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ArchiveHead from './ArchiveHead.svelte';

const show = (over: Partial<View>, total: number | null = null) =>
	render(ArchiveHead, { view: { ...NOWHERE, ...over }, total });

test('the way back is to the archive, not to the river', async () => {
	const screen = await show({ q: 'from:pluralistic' });

	await expect
		.element(screen.getByRole('link', { name: /Archive/ }))
		.toHaveAttribute('href', '/archive');
});

// The query is the only thing naming this list, so it has to be in the field you edit
// rather than printed above one that is empty.
test('the field carries the query, so narrowing it is one keystroke', async () => {
	const screen = await show({ q: 'density from:pluralistic' }, 17);

	await expect
		.element(screen.getByRole('searchbox', { name: /Search the archive/ }))
		.toHaveValue('density from:pluralistic');
});

test('how much it reached is the one number the archive does carry', async () => {
	const screen = await show({ q: 'density' }, 17);

	expect(screen.container.querySelector('.tally')!.textContent).toBe('17 pieces');
});

test('and one piece is not called pieces', async () => {
	const screen = await show({ q: 'wombat' }, 1);

	expect(screen.container.querySelector('.tally')!.textContent).toBe('1 piece');
});

test('nothing reached says nought rather than nothing at all', async () => {
	const screen = await show({ q: 'wombat' }, 0);

	expect(screen.container.querySelector('.tally')!.textContent).toBe('0 pieces');
});
