// What `ui/search.py` wraps a match in. Control characters rather than markup, so the
// fragment survives being flattened from markdown and is still rendered as text.
const OPEN = '\x02';
const CLOSE = '\x03';

export type Run = { text: string; hit: boolean };

/** A fragment as runs of text, each saying whether it is what the search matched. */
export function marked(snippet: string): Run[] {
	return snippet
		.split(OPEN)
		.flatMap((part, index) => (index === 0 ? [[part, false] as const] : split(part)))
		.filter(([text]) => text)
		.map(([text, hit]) => ({ text, hit }));
}

function split(part: string): (readonly [string, boolean])[] {
	const close = part.indexOf(CLOSE);
	// An unclosed marker means the snippet was cut mid-match; the rest is still prose.
	if (close < 0) return [[part, true] as const];
	return [
		[part.slice(0, close), true] as const,
		[part.slice(close + CLOSE.length), false] as const,
	];
}
