// One question asked of every screen: does anything run through the margin? The answers
// that get it wrong are always the same two — a number nobody sized the column for, and a
// run of text that cannot break. So each of these is rendered at the narrowest phone
// there is, with the longest thing it will ever be handed.
import type { Contents, Entry, Following, Listing } from '#lib/api/client.ts';
import { NOWHERE, type View } from '#lib/links.ts';
import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ArchiveHead from './ArchiveHead.svelte';
import ContentsView from './Contents.svelte';
import Feeds from './Feeds.svelte';
import Masthead from './Masthead.svelte';
import River from './River.svelte';
import SectionStrip from './SectionStrip.svelte';

vi.mock('$app/state', () => ({ navigating: { to: null } }));
vi.mock('$app/navigation', () => ({ goto: () => {}, invalidateAll: () => {} }));
vi.mock('#lib/api/client.ts', () => ({ listing: () => new Promise(() => {}) }));

const NARROW = 320;

const LONG_NAME = 'The Institute for the Study of Very Long Publication Names Quarterly';
const LONG_TEXT =
	'Holly Tregenza, Courtney Gould and the ABC News Digital Investigations Unit in Canberra';
const BIG = 987654;

/** Whether anything between this and the margin handles its own overflow. */
function scrolled(el: HTMLElement, container: HTMLElement): boolean {
	for (let at: HTMLElement | null = el; at && at !== container; at = at.parentElement) {
		if (getComputedStyle(at).overflowX !== 'visible') return true;
	}
	return false;
}

/** Everything on screen that reaches past the right-hand margin. */
function through(container: HTMLElement): string[] {
	const edge = container.getBoundingClientRect().right;
	return [...container.querySelectorAll<HTMLElement>('*')]
		.filter((el) => !scrolled(el, container))
		.filter((el) => el.getBoundingClientRect().right - edge > 1)
		.map((el) => `${el.tagName.toLowerCase()}.${el.className}`);
}

/** Rendered on a phone rather than on whatever width the runner happens to have. */
async function narrow<T>(component: T, props: Record<string, unknown>) {
	const screen = await render(component as never, props as never);
	const container = screen.container as HTMLElement;
	container.style.width = `${NARROW}px`;
	return container;
}

const view = (over: Partial<View> = {}): View => ({ ...NOWHERE, ...over });

test('the masthead, with the longest dateline it has and the archive beside it', async () => {
	const container = await narrow(Masthead, { view: view({ month: '2026-09' }), updated: null });

	expect(through(container)).toEqual([]);
});

test('the archive, with a six-figure count against a name that will not fit', async () => {
	const held: Contents = {
		items: BIG,
		months: [{ month: '2026-09', items: BIG }],
		feeds: [
			{
				feed_id: 'f1',
				title: LONG_NAME,
				url: 'https://example.com/feed',
				tier: 'kindle',
				dropped: false,
				items: BIG,
				latest: new Date().toISOString(),
			},
		],
		updated: null,
	};

	const container = await narrow(ContentsView, { held });

	expect(through(container)).toEqual([]);
});

test('a shelf header, with a publication and a month named at once', async () => {
	const container = await narrow(ArchiveHead, {
		view: view({ feed: 'f1', month: '2026-09' }),
		shelf: LONG_NAME,
		total: BIG,
	});

	expect(through(container)).toEqual([]);
});

test('a river row, with a whole production credit for a byline', async () => {
	const entry: Entry = {
		id: 'aaaaaaaa-0000-4000-8000-000000000001',
		title: LONG_NAME,
		url: 'https://example.com/a',
		outlet: LONG_NAME,
		author: LONG_TEXT,
		published_at: null,
		first_seen_at: new Date().toISOString(),
		read: false,
		sent: true,
		queued: false,
		snippet: '',
	};
	const page: Listing = { entries: [entry], cursor: '', updated: null, shelf: '' };

	const container = await narrow(River, { page, view: view(), selected: '' });

	expect(through(container)).toEqual([]);
});

test('a followed feed, with a title and an address that both run long', async () => {
	const feed: Following = {
		id: 'aaaaaaaa-0000-4000-8000-000000000001',
		title: LONG_NAME,
		url: 'https://example.com/very/long/path/to/somebodys/feed/that/keeps/going.xml',
		site_url: 'https://example.com',
		category: 'Investigations and Long Form',
		tier: 'kindle',
		expires_after_seconds: 2592000,
		last_success_at: null,
	};

	const container = await narrow(Feeds, {
		feeds: [feed],
		sections: ['Investigations and Long Form'],
	});

	expect(through(container)).toEqual([]);
});

test('the section strip, which scrolls rather than wrapping', async () => {
	const container = await narrow(SectionStrip, {
		sections: [
			'Investigations and Long Form',
			'Science and the Environment',
			'Everything Else',
		],
		current: '',
	});

	expect(through(container)).toEqual([]);
});
