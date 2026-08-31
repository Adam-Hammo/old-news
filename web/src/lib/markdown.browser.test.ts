import { expect, test } from 'vitest';
import { render } from './markdown.ts';

test('markdown becomes the html an article is set in', () => {
	expect(render('A **bold** word.')).toContain('<strong>bold</strong>');
});

test('a link keeps its anchor and its target', () => {
	const html = render('See [the report](https://example.com/a).');

	expect(html).toContain('href="https://example.com/a"');
	expect(html).toContain('the report');
});

// The body is a publisher's, read out of a page nobody here controls.
test('a script smuggled through the extractor does not survive', () => {
	const html = render('Text.\n\n<script>window.stolen = 1;</script>');

	expect(html).not.toContain('<script');
	expect(html).toContain('Text.');
});

test('nor does an event handler hiding on an image', () => {
	expect(render('<img src=x onerror="window.stolen = 1">')).not.toContain('onerror');
});
