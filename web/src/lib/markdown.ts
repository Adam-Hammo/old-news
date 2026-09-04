import DOMPurify from 'dompurify';
import { Marked, type Tokens } from 'marked';
import { BASE } from '#lib/api/client.ts';

// What the API rewrites a held picture's address to. It is an API path like any other,
// so it needs the API's prefix — an `<img src="/images/…">` would otherwise ask the node
// process serving this page.
const HELD = '/images/';

// An instance of its own, so overriding one rule does not reach every other caller of
// `marked`. Built once: the parser is stateless between renders.
const parser = new Marked({ gfm: true, breaks: false, async: false });

parser.use({
	renderer: {
		image(token: Tokens.Image): string {
			const href = token.href.startsWith(HELD) ? `${BASE}${token.href}` : token.href;
			const title = token.title ? ` title="${token.title}"` : '';
			return `<img src="${href}" alt="${token.text}"${title}>`;
		},
	},
});

/** Extraction output is markdown. Publisher text, so it is scrubbed on the way out. */
export function render(body: string): string {
	return DOMPurify.sanitize(parser.parse(body, { async: false }));
}
