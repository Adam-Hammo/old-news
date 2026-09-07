/** Which screen, and which slice of it. The river has sections; the archive has a query. */
export type View = { archive: boolean; section: string; q: string };

export const NOWHERE: View = { archive: false, section: '', q: '' };
export const EVERYTHING: View = { archive: true, section: '', q: '' };

/** In the archive rather than the river. It is the path that says so, not the query: the
 *  archive with nothing typed into it is still the archive. */
export function archived(view: View): boolean {
	return view.archive;
}

function query(view: View): string {
	// `encodeURIComponent`, not `URLSearchParams`: that spells a space `+`, and the rest
	// of the app spells it `%20`. Two spellings of one view is two URLs for one screen.
	const value = view.archive ? view.q : view.section;
	if (!value) return '';
	return `?${view.archive ? 'q' : 'section'}=${encodeURIComponent(value)}`;
}

export function list(view: View): string {
	return `${view.archive ? '/archive' : '/'}${query(view)}`;
}

/** The archive with nothing asked of it, which is everything it holds. */
export function archive(): string {
	return list(EVERYTHING);
}

export function section(name: string): string {
	return list({ ...NOWHERE, section: name });
}

/** An article keeps the screen it was opened from: the archive covers, the river sits beside. */
export function item(id: string, view: View): string {
	return `${view.archive ? '/archive' : ''}/item/${id}${query(view)}`;
}

export function search(terms: string): string {
	return list({ ...EVERYTHING, q: terms });
}

/** A name with a space in it has to survive the split, and quoting is what does that. */
function named(value: string): string {
	return /\s/.test(value) ? `"${value}"` : value;
}

/** One term added to whatever is already typed, which is what clicking the rail does. */
export function and(view: View, term: string): string {
	const already = view.q.trim();
	return search(already ? `${already} ${term}` : term);
}

export function from(title: string): string {
	return `from:${named(title)}`;
}

/** `2026-06` as the pair of dates the grammar spells a month with. */
export function within(name: string): string {
	const [year, ordinal] = name.split('-').map(Number);
	if (!year || !ordinal) return name;
	const next = `${year + Math.floor(ordinal / 12)}-${String((ordinal % 12) + 1).padStart(2, '0')}`;
	return `after:${name} before:${next}`;
}

/** `2026-06` as the reader's own words for it. The archive labels months; this reads them. */
export function volume(name: string): string {
	const [year, ordinal] = name.split('-').map(Number);
	if (!year || !ordinal) return name;
	return new Date(Date.UTC(year, ordinal - 1, 1)).toLocaleDateString(undefined, {
		month: 'long',
		year: 'numeric',
		timeZone: 'UTC',
	});
}
