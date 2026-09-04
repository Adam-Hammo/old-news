import DOMPurify from 'dompurify';
import { Marked, type Tokens } from 'marked';
import { held } from '#lib/api/client.ts';

// An instance of its own, so overriding one rule does not reach every other caller of
// `marked`. Built once: the parser is stateless between renders.
const parser = new Marked({ gfm: true, breaks: false, async: false });

parser.use({
	renderer: {
		image(token: Tokens.Image): string {
			const title = token.title ? ` title="${token.title}"` : '';
			return `<img src="${held(token.href)}" alt="${token.text}"${title}>`;
		},
	},
});

/** Extraction output is markdown. Publisher text, so it is scrubbed on the way out. */
export function render(body: string): string {
	return DOMPurify.sanitize(parser.parse(body, { async: false }));
}
