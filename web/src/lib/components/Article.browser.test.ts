import type { Article } from '#lib/api/client.ts';
import { page } from 'vitest/browser';
import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ArticleView from './Article.svelte';

function article(over: Partial<Article> = {}): Article {
	return {
		id: 'aaaaaaaa-0000-4000-8000-000000000001',
		title: 'A quiet street in Leeds',
		url: 'https://example.com/a',
		outlet: 'The Guardian',
		author: 'Priya Raman',
		feed_body: '',
		page_body: 'The residents have been **told** the smell is seasonal.',
		reading: 'page',
		published_at: '2026-08-30T06:46:00Z',
		first_seen_at: '2026-08-30T07:00:00Z',
		read: false,
		comments_url: '',
		versions: 1,
		section: 'Surveillance',
		...over,
	};
}

test('the headline, the byline and the text', async () => {
	const screen = await render(ArticleView, { article: article(), back: '/' });

	await expect
		.element(screen.getByRole('heading', { level: 1 }))
		.toHaveTextContent('A quiet street in Leeds');
	await expect.element(screen.getByText('The Guardian')).toBeVisible();
	await expect.element(screen.getByText('Priya Raman')).toBeVisible();
	expect(screen.container.querySelector('.body strong')?.textContent).toBe('told');
});

test('an author nobody recorded leaves no stray separator', async () => {
	const screen = await render(ArticleView, { article: article({ author: '' }), back: '/' });

	const byline = screen.container.querySelector('.by')!;
	expect(byline.querySelectorAll('span')).toHaveLength(2);
});

// Extraction lags ingest, so an article can arrive before its text does.
test('an article with nothing extracted yet says so', async () => {
	const screen = await render(ArticleView, { article: article({ page_body: '' }), back: '/' });

	await expect
		.element(screen.getByText(/No text has been read out of this one yet/))
		.toBeVisible();
});

test('back to the river is the whole of the navigation', async () => {
	const screen = await render(ArticleView, { article: article(), back: '/?section=Science' });

	for (const link of screen.container.querySelectorAll('a[href^="/"]')) {
		expect(link.getAttribute('href')).toBe('/?section=Science');
	}
	// No Next: with no Prev beside it, one mis-tap loses the article.
	expect(screen.container.querySelector('.bar')!.querySelectorAll('a')).toHaveLength(1);
});

test('the actions are behind the overflow control, not on the bar', async () => {
	const screen = await render(ArticleView, { article: article(), back: '/' });

	const sheet = screen.container.querySelector('dialog');
	expect(sheet?.open).toBeFalsy();

	await screen.getByRole('button', { name: 'Article actions' }).click();

	expect(sheet?.open).toBe(true);
	await expect
		.element(screen.getByRole('link', { name: /Read the original/ }))
		.toHaveAttribute('href', 'https://example.com/a');
});

test('comments are offered only where the feed gave one', async () => {
	const without = await render(ArticleView, { article: article(), back: '/' });
	expect(without.container.querySelector('dialog')?.querySelectorAll('a')).toHaveLength(1);
	await without.unmount();

	const withUrl = await render(ArticleView, {
		article: article({ comments_url: 'https://example.com/a#comments' }),
		back: '/',
	});
	expect(withUrl.container.querySelector('dialog')?.querySelectorAll('a')).toHaveLength(2);
});

// A row cannot carry a kicker — a section is a set of feeds — but one article has one feed.
test('the kicker is the section, and absent when the feed is unfiled', async () => {
	const filed = await render(ArticleView, { article: article(), back: '/' });
	await expect.element(filed.getByText('Surveillance')).toBeVisible();
	await filed.unmount();

	const loose = await render(ArticleView, { article: article({ section: '' }), back: '/' });
	expect(loose.container.querySelector('.kicker')).toBeNull();
});

test('the headline is followed by the byline, with nothing derived in between', async () => {
	const screen = await render(ArticleView, { article: article(), back: '/' });

	expect(screen.container.querySelector('h1 + .hair')).not.toBeNull();
});

test('the version count shows only when there is more than one to choose between', async () => {
	const one = await render(ArticleView, { article: article(), back: '/' });
	expect(one.container.querySelector('.by em')).toBeNull();
	await one.unmount();

	const three = await render(ArticleView, { article: article({ versions: 3 }), back: '/' });
	await expect.element(three.getByText('v3 of 3')).toBeVisible();
});

// A desktop pane is wider than `--measure`, and the slack is a margin either side of the
// column rather than all of it on the right.
test('the column is centred in the pane, with the back-link on the same edges', async () => {
	await page.viewport(1010, 900);
	const screen = await render(ArticleView, { article: article(), back: '/' });

	const pane = screen.container.querySelector('.pane')!.getBoundingClientRect();
	const column = screen.container.querySelector('article')!.getBoundingClientRect();
	const top = screen.container.querySelector('.top')!.getBoundingClientRect();

	expect(pane.width).toBeGreaterThan(column.width);
	expect(column.left - pane.left).toBeCloseTo(pane.right - column.right, 0);
	expect(top.left).toBeCloseTo(column.left, 0);
	expect(top.right).toBeCloseTo(column.right, 0);
});

test('the body is justified, which is why the column is measured', async () => {
	const screen = await render(ArticleView, { article: article(), back: '/' });

	const paragraph = screen.container.querySelector('.body p')!;
	expect(getComputedStyle(paragraph).textAlign).toBe('justify');
});

const TEASER = 'The teaser, which is all the feed carried.';

test('the toggle sits in the byline and swaps the text under it', async () => {
	const screen = await render(ArticleView, {
		article: article({ feed_body: TEASER }),
		back: '/',
	});

	await expect
		.element(screen.getByRole('button', { name: 'Web' }))
		.toHaveAttribute('aria-pressed', 'true');

	await screen.getByRole('button', { name: 'Feed' }).click();

	await expect.element(screen.getByText(TEASER)).toBeVisible();
	await expect
		.element(screen.getByRole('button', { name: 'Feed' }))
		.toHaveAttribute('aria-pressed', 'true');
});

test('one reading leaves nothing to toggle between', async () => {
	const screen = await render(ArticleView, { article: article(), back: '/' });

	expect(screen.container.querySelector('.meta')).toBeNull();
});

test('the version count keeps its corner when the toggle joins it', async () => {
	const screen = await render(ArticleView, {
		article: article({ feed_body: TEASER, versions: 3 }),
		back: '/',
	});

	await expect.element(screen.getByText('v3 of 3')).toBeVisible();
	expect(screen.container.querySelectorAll('.meta button')).toHaveLength(2);
});
