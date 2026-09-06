/** Which list a screen is showing. The river slices by section; the archive by shelf. */
export type View = { section: string; feed: string; month: string; tier: string; q: string };

export const NOWHERE: View = { section: '', feed: '', month: '', tier: '', q: '' };

/** In the archive rather than the river: a publication, a month, or a search. */
export function archived(view: View): boolean {
	return Boolean(view.feed || view.month || view.q);
}

function query(view: View): string {
	// `encodeURIComponent`, not `URLSearchParams`: that spells a space `+`, and the rest
	// of the app spells it `%20`. Two spellings of one view is two URLs for one screen.
	// A search is its own view: the shelf keys are not sent with it, so a URL carrying
	// both would claim a filter the results do not have.
	const pairs = view.q
		? [`q=${encodeURIComponent(view.q)}`]
		: archived(view)
			? [
					view.feed ? `feed=${encodeURIComponent(view.feed)}` : '',
					view.month ? `month=${encodeURIComponent(view.month)}` : '',
					view.tier ? `tier=${encodeURIComponent(view.tier)}` : '',
				]
			: [view.section ? `section=${encodeURIComponent(view.section)}` : ''];
	const set = pairs.filter(Boolean);
	return set.length ? `?${set.join('&')}` : '';
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

/** The contents page. Every shelf is reached from it, and it is reached from every shelf. */
export function contents(): string {
	return '/archive';
}

export function feed(id: string): string {
	return list({ ...NOWHERE, feed: id });
}

export function month(name: string, tier = ''): string {
	return list({ ...NOWHERE, month: name, tier });
}

export function search(terms: string): string {
	return list({ ...NOWHERE, q: terms });
}

/** The same shelf with the wire left in or taken out, which is the one filter a month needs. */
export function wire(view: View, showing: boolean): string {
	return list({ ...view, tier: showing ? '' : 'archive' });
}

/** `2026-06` as the reader's own words for it. The archive labels shelves; this reads them. */
export function volume(name: string): string {
	const [year, month] = name.split('-').map(Number);
	if (!year || !month) return name;
	return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(undefined, {
		month: 'long',
		year: 'numeric',
		timeZone: 'UTC',
	});
}
