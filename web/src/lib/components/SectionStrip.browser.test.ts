import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import SectionStrip from './SectionStrip.svelte';

const FEW = ['Science', 'Technology'];
const MANY = ['Business', 'Cities', 'Culture', 'Long form', 'Politics', 'Science', 'Sport'];

test('the whole river is the default view, and it is called Everything', async () => {
	const screen = await render(SectionStrip, { sections: FEW, current: '' });

	const names = [...screen.container.querySelectorAll('.strip a')].map((a) =>
		a.textContent?.trim(),
	);
	expect(names).toEqual(['Everything', 'Science', 'Technology']);
});

test('the section being read is the one marked', async () => {
	const screen = await render(SectionStrip, { sections: FEW, current: 'Science' });

	await expect.element(screen.getByRole('link', { name: 'Science' })).toHaveClass(/\bcurrent\b/);
	await expect
		.element(screen.getByRole('link', { name: 'Everything' }))
		.not.toHaveClass(/current/);
});

// Picking a section is a river action, so it goes to the river rather than staying on
// whatever article happens to be open.
test('a section link goes back to the river', async () => {
	const screen = await render(SectionStrip, { sections: FEW, current: '' });

	await expect
		.element(screen.getByRole('link', { name: 'Science' }))
		.toHaveAttribute('href', '/?section=Science');
	await expect
		.element(screen.getByRole('link', { name: 'Everything' }))
		.toHaveAttribute('href', '/');
});

// Pinned rather than conditional: it sits outside the scroll behind a rule, so the strip's
// height never changes and nothing is ever unreachable.
test('the pinned control is there whether or not the strip overflows', async () => {
	const few = await render(SectionStrip, { sections: FEW, current: '' });
	await expect.element(few.getByRole('button', { name: /All/ })).toBeVisible();
	await few.unmount();

	const many = await render(SectionStrip, { sections: MANY, current: '' });
	await expect.element(many.getByRole('button', { name: /All/ })).toBeVisible();
});

test('it opens a sheet listing every section, not just the ones that overflowed', async () => {
	const screen = await render(SectionStrip, { sections: MANY, current: '' });

	await screen.getByRole('button', { name: /All/ }).click();

	const sheet = screen.container.querySelector('dialog')!;
	expect(sheet.open).toBe(true);
	const listed = [...sheet.querySelectorAll('a')].map((a) => a.textContent?.trim());
	expect(listed).toEqual(['Everything', ...MANY]);
});
