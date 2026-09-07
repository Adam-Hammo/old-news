/** Which list a screen is showing. The river slices by section; the archive by query. */
export type View = { section: string; q: string };

export const NOWHERE: View = { section: '', q: '' };

/** In the archive rather than the river, which is anything the query reaches. */
export function archived(view: View): boolean {
	return Boolean(view.q);
}

function query(view: View): string {
	// `encodeURIComponent`, not `URLSearchParams`: that spells a space `+`, and the rest
	// of the app spells it `%20`. Two spellings of one view is two URLs for one screen.
	// A query is its own view: the river's section is not sent with it, because the
	// archive does not have sections.
	const pair = view.q
		? `q=${encodeURIComponent(view.q)}`
		: view.section
			? `section=${encodeURIComponent(view.section)}`
			: '';
	return pair ? `?${pair}` : '';
}

export function list(view: View): string {
	return `/${query(view)}`;
}

export function section(name: string): string {
	return list({ ...NOWHERE, section: name });
}

export function item(id: string, view: View): string {
	return `/item/${id}${query(view)}`;
}

/** The contents page. Every query is reached from it, and it is reached from every query. */
export function contents(): string {
	return '/archive';
}

export function search(terms: string): string {
	return list({ ...NOWHERE, q: terms });
}

/** A name with a space in it has to survive the split, and quoting is what does that. */
function named(value: string): string {
	return /\s/.test(value) ? `"${value}"` : value;
}

export function publication(title: string): string {
	return search(`from:${named(title)}`);
}

/** `2026-06` as the pair of dates the grammar spells a month with. */
export function month(name: string): string {
	const [year, ordinal] = name.split('-').map(Number);
	if (!year || !ordinal) return search(name);
	const following = `${year + Math.floor(ordinal / 12)}-${String((ordinal % 12) + 1).padStart(2, '0')}`;
	return search(`after:${name} before:${following}`);
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
