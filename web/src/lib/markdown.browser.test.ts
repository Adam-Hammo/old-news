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

// Two things the extractor now puts in a body that nothing here used to be shown.
test('a quoted block is set as a quotation, not as the surrounding prose', () => {
	const html = render('The minister said this:\n\n> We heard you.\n\nNobody believed it.');

	expect(html).toContain('<blockquote>');
	expect(html).toContain('We heard you.');
});

// An item that is a comic or a photo has nothing else in it.
test('a picture survives with the words the publisher hung off it', () => {
	const html = render(
		'![Geology Class](https://imgs.example.com/c.png "The joke, in the title.")',
	);

	expect(html).toContain('src="https://imgs.example.com/c.png"');
	expect(html).toContain('alt="Geology Class"');
	expect(html).toContain('title="The joke, in the title."');
});

test("a held picture is asked of the api, not of the page's own origin", () => {
	const html = render('![a chart](/images/aaaaaaaa-0000-4000-8000-000000000001/)');

	expect(html).toContain('src="/api/images/aaaaaaaa-0000-4000-8000-000000000001/"');
	expect(html).toContain('alt="a chart"');
});

// The API leaves these alone, and so must the prefix.
test("a publisher's own picture is left where it is", () => {
	expect(render('![a chart](https://cdn.example.com/a.png)')).toContain(
		'src="https://cdn.example.com/a.png"',
	);
});
