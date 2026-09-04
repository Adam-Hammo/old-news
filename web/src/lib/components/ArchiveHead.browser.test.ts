import { NOWHERE, type View } from '#lib/links.ts';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ArchiveHead from './ArchiveHead.svelte';

const show = (over: Partial<View>, shelf = '') =>
	render(ArchiveHead, { view: { ...NOWHERE, ...over }, shelf });

// A publication's title is the one thing the URL cannot carry, so the archive sends it.
test('a publication shelf is named by what the archive called it', async () => {
	const screen = await show({ feed: 'f1' }, 'Construction Physics');

	expect(screen.container.querySelector('.named')!.textContent).toBe('Construction Physics');
});

test('a month names itself, so nothing has to be fetched to label it', async () => {
	const screen = await show({ month: '2026-06' });

	expect(screen.container.querySelector('.named')!.textContent).toBe('June 2026');
});

test('a publication within a month says both', async () => {
	const screen = await show({ feed: 'f1', month: '2026-06' }, 'Construction Physics');

	expect(screen.container.querySelector('.named')!.textContent).toBe(
		'Construction Physics, June 2026',
	);
});

test('the way back is to the contents, not to the river', async () => {
	const screen = await show({ feed: 'f1' }, 'Construction Physics');

	await expect
		.element(screen.getByRole('link', { name: /Contents/ }))
		.toHaveAttribute('href', '/archive');
});

// A month is mostly wire; a publication is one tier already, so the sift would do nothing.
test('a month offers to leave the wire off', async () => {
	const screen = await show({ month: '2026-06' });

	await expect
		.element(screen.getByRole('link', { name: 'Without the wire' }))
		.toHaveAttribute('href', '/?month=2026-06&tier=archive');
});

test('and offers it back once it is off', async () => {
	const screen = await show({ month: '2026-06', tier: 'archive' });

	await expect
		.element(screen.getByRole('link', { name: 'With the wire' }))
		.toHaveAttribute('href', '/?month=2026-06');
});

test('a publication shelf offers no sift, because it is one tier already', async () => {
	const screen = await show({ feed: 'f1' }, 'Construction Physics');

	expect(screen.container.querySelector('.sift')).toBeNull();
});

// A search is in the archive too, and the one thing a search needs that a shelf does not
// is how much it turned up.
test('a search carries the field it was typed into, so narrowing it is one keystroke', async () => {
	const screen = await render(ArchiveHead, {
		view: { ...NOWHERE, q: 'housing density' },
		shelf: '',
		total: 17,
	});

	await expect
		.element(screen.getByRole('searchbox', { name: /Search the archive/ }))
		.toHaveValue('housing density');
	expect(screen.container.querySelector('.tally')!.textContent).toBe('17 matches');
});

test('and one match is not called matches', async () => {
	const screen = await render(ArchiveHead, {
		view: { ...NOWHERE, q: 'wombat' },
		shelf: '',
		total: 1,
	});

	expect(screen.container.querySelector('.tally')!.textContent).toBe('1 match');
});

// The river has no total by design and a shelf's is on the contents page already.
test('a shelf shows no count at all', async () => {
	const screen = await show({ feed: 'f1' }, 'Construction Physics');

	expect(screen.container.querySelector('.tally')).toBeNull();
});
