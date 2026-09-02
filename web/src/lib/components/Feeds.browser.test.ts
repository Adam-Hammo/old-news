import type { Following } from '#lib/api/client.ts';
import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Feeds from './Feeds.svelte';

const calls = vi.hoisted(() => [] as string[]);
const fails = vi.hoisted(() => ({ with: '' }));

vi.mock('$app/navigation', () => ({ invalidateAll: () => Promise.resolve() }));
vi.mock('#lib/api/client.ts', () => ({
	follow: (url: string, category: string) => {
		calls.push(`follow ${url} ${category}`);
		return Promise.resolve(fails.with);
	},
	file: (id: string, category: string) => {
		calls.push(`file ${id} ${category}`);
		return Promise.resolve(fails.with);
	},
	unfollow: (id: string) => {
		calls.push(`unfollow ${id}`);
		return Promise.resolve(fails.with);
	},
}));

function feed(over: Partial<Following> = {}): Following {
	return {
		id: 'aaaaaaaa-0000-4000-8000-000000000001',
		title: 'Astral Codex Ten',
		url: 'https://astralcodexten.com/feed',
		site_url: '',
		category: 'Edition',
		last_success_at: null,
		...over,
	};
}

function setup(feeds: Following[], sections: string[] = []) {
	calls.length = 0;
	fails.with = '';
	return render(Feeds, { feeds, sections });
}

test('feeds are grouped under the section they are filed in', async () => {
	const screen = await setup([
		feed({ category: 'Science', title: 'Nautilus' }),
		feed({ id: 'bbbbbbbb-0000-4000-8000-000000000002', category: 'Edition' }),
	]);

	const headings = [...screen.container.querySelectorAll('h3')].map((h) => h.textContent);
	expect(headings).toEqual(['Edition', 'Science']);
});

// Unfiled is the absence of a section, not one more of them, so it sorts last.
test('unfiled feeds come after the sections', async () => {
	const screen = await setup([
		feed({ category: '', title: 'Loose' }),
		feed({ id: 'bbbbbbbb-0000-4000-8000-000000000002', category: 'Science' }),
	]);

	const headings = [...screen.container.querySelectorAll('h3')].map((h) => h.textContent);
	expect(headings).toEqual(['Science', 'Unfiled']);
});

test('a pasted address is followed, with the section given', async () => {
	const screen = await setup([]);

	await screen.getByLabelText('Feed or site address').fill('https://example.com');
	await screen.getByLabelText('Section').fill('Technology');
	await screen.getByRole('button', { name: 'Follow' }).click();

	await expect.poll(() => calls).toEqual(['follow https://example.com Technology']);
});

test('a feed is refiled by typing another section against it', async () => {
	const screen = await setup([feed()]);

	await screen.getByLabelText('Section for Astral Codex Ten').fill('Science');
	// `change` rather than every keystroke, or a half-typed section gets saved.
	await screen
		.getByLabelText('Section for Astral Codex Ten')
		.element()
		.dispatchEvent(new Event('change', { bubbles: true }));

	await expect.poll(() => calls).toEqual(['file aaaaaaaa-0000-4000-8000-000000000001 Science']);
});

// One press was the whole gesture, and the thing it takes away is a poll history.
test('a feed is dropped by its own control, on the second press', async () => {
	const screen = await setup([feed()]);

	await screen.getByRole('button', { name: 'Drop Astral Codex Ten' }).click();
	expect(calls).toEqual([]);

	await screen.getByRole('button', { name: 'Confirm dropping Astral Codex Ten' }).click();

	await expect.poll(() => calls).toEqual(['unfollow aaaaaaaa-0000-4000-8000-000000000001']);
});

test('an armed drop stands down when it is left alone', async () => {
	const screen = await setup([feed()]);
	const button = screen.getByRole('button', { name: 'Drop Astral Codex Ten' }).element();

	await screen.getByRole('button', { name: 'Drop Astral Codex Ten' }).click();
	(button as HTMLElement).blur();

	await expect
		.element(screen.getByRole('button', { name: 'Drop Astral Codex Ten' }))
		.toBeVisible();
	expect(calls).toEqual([]);
});

// The API knows why it refused; the screen only has to say it.
test('what the API refused is said on the screen', async () => {
	const screen = await setup([]);
	fails.with = 'already following that one';

	await screen.getByLabelText('Feed or site address').fill('https://example.com');
	await screen.getByRole('button', { name: 'Follow' }).click();

	await expect.element(screen.getByRole('alert')).toHaveTextContent('already following that one');
});

test('the address is kept when following it failed, so it can be corrected', async () => {
	const screen = await setup([]);
	fails.with = 'no feed there, and the page names none';

	await screen.getByLabelText('Feed or site address').fill('https://example.com/nope');
	await screen.getByRole('button', { name: 'Follow' }).click();

	await expect
		.element(screen.getByLabelText('Feed or site address'))
		.toHaveValue('https://example.com/nope');
});

test('sections already in use are offered rather than typed from memory', async () => {
	const screen = await setup([feed({ category: 'Edition' })], ['Science', 'Edition']);

	const offered = [...screen.container.querySelectorAll('datalist option')].map((o) =>
		o.getAttribute('value'),
	);
	expect(offered).toEqual(['Edition', 'Science']);
});

test('nothing followed says so rather than showing an empty rule', async () => {
	const screen = await setup([]);

	await expect.element(screen.getByText('Nothing followed yet.')).toBeVisible();
});
