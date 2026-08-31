import DOMPurify from 'dompurify';
import { marked } from 'marked';

/** Extraction output is markdown. Publisher text, so it is scrubbed on the way out. */
export function render(body: string): string {
	return DOMPurify.sanitize(marked.parse(body, { async: false, gfm: true, breaks: false }));
}
