// One question asked of every screen: does anything run through the margin? The answers
// that get it wrong are always the same two — a number nobody sized the column for, and a
// run of text that cannot break. So each of these is rendered at the narrowest phone
// there is, with the longest thing it will ever be handed.
import type {
	Contents,
	Entry,
	Following,
	Listing,
	Polling as Poll,
	Publisher,
	Section,
} from '#lib/api/client.ts';
import { NOWHERE, type View } from '#lib/links.ts';
import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ArchiveHead from './ArchiveHead.svelte';
import Config from './Config.svelte';
import ContentsView from './Contents.svelte';
import Feeds from './Feeds.svelte';
import Masthead from './Masthead.svelte';
import Polling from './Polling.svelte';
import Publishers from './Publishers.svelte';
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

test("a feed in trouble, with the publisher's own words for why", async () => {
	const feed: Poll = {
		id: 'aaaaaaaa-0000-4000-8000-000000000001',
		title: LONG_NAME,
		url: 'https://example.com/feed.xml',
		category: 'Investigations and Long Form',
		last_polled_at: new Date().toISOString(),
		last_success_at: null,
		next_poll_at: new Date().toISOString(),
		consecutive_failures: BIG,
		gone: false,
		outcome: 'failed',
		status: 503,
		error:
			'httpx.ConnectError: [Errno -2] Name or service not known ' +
			'while requesting https://example.com/a/very/long/path/nobody/can/break.xml',
	};

	const container = await narrow(Polling, { feeds: [feed] });

	expect(through(container)).toEqual([]);
});

test('a publisher, with every fact it can carry at once', async () => {
	const host: Publisher = {
		name: 'a-very-long-publisher-hostname-that-nobody-would-register.example.com',
		feeds: BIG,
		requires_www: true,
		crawl_delay_seconds: 120,
		robots_status: 503,
		robots_fetched_at: new Date().toISOString(),
		robots_expires_at: new Date().toISOString(),
		capture_failures: BIG,
	};

	const container = await narrow(Publishers, { hosts: [host] });

	expect(through(container)).toEqual([]);
});

// A user agent is one word as far as the browser is concerned, and it is the longest
// setting there is.
test('the config, with a setting whose value cannot break', async () => {
	const config: Section[] = [
		{
			name: 'http',
			settings: [
				{
					name: 'user_agent',
					value: 'old-news/0.1 (+https://github.com/Adam-Hammo/old-news)',
				},
				{ name: 'max_body_bytes', value: String(16 * 1024 * 1024) },
			],
		},
	];

	const container = await narrow(Config, { config });

	expect(through(container)).toEqual([]);
});
