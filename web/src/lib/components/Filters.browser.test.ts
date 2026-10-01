import type { Blocking, Following } from '#lib/api/client.ts';
import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import Filters from './Filters.svelte';

const calls = vi.hoisted(() => [] as string[]);

vi.mock('$app/navigation', () => ({ invalidateAll: () => Promise.resolve() }));
vi.mock('#lib/api/client.ts', () => ({
	block: (filter: Record<string, unknown>) => {
		calls.push(`block ${JSON.stringify(filter)}`);
		return Promise.resolve('');
	},
	unblock: (id: string) => {
		calls.push(`unblock ${id}`);
		return Promise.resolve('');
	},
}));

const FEED: Following = {
	id: 'aaaaaaaa-0000-4000-8000-000000000001',
	title: 'The Guardian',
	url: 'https://theguardian.com/rss',
	site_url: '',
	category: '',
	tier: 'wire',
	expires_after_seconds: 2592000,
	last_success_at: null,
};

const LIVE: Blocking = {
	id: 'bbbbbbbb-0000-4000-8000-000000000002',
	dimension: 'url_pattern',
	pattern: '/live/',
	feed_id: FEED.id,
	feed: 'The Guardian',
	source: 'seed',
	note: '',
};

function setup(filters: Blocking[] = []) {
	calls.length = 0;
	return render(Filters, { filters, feeds: [FEED] });
}

test('a filter is added for the feed picked, trimmed', async () => {
	const screen = await setup();

	await screen.getByLabelText('Feed').selectOptions('The Guardian');
	await screen.getByLabelText('Pattern').fill('  live:  ');
	await screen.getByRole('button', { name: 'Block' }).click();

	await expect
		.poll(() => calls)
		.toEqual([
			`block ${JSON.stringify({ dimension: 'title_phrase', pattern: 'live:', feed_id: FEED.id, note: '' })}`,
		]);
});

test('removing takes a second press', async () => {
	const screen = await setup([LIVE]);
	const remove = screen.getByRole('button', { name: 'Remove /live/' });

	await remove.click();
	expect(calls).toEqual([]);
	await screen.getByRole('button', { name: 'Confirm removing /live/' }).click();

	await expect.poll(() => calls).toEqual([`unblock ${LIVE.id}`]);
});
