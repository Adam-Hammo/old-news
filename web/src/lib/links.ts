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

/** A name with a space in it has to survive the split, and quoting is what does that.
 *  A quote of its own cannot be spelt inside one, so it comes out — the match is a
 *  substring either way, so the shorter name still finds the thing. */
function named(value: string): string {
	const plain = value.replaceAll('"', '').trim();
	return /\s/.test(plain) ? `"${plain}"` : plain;
}

/** The query as its terms, with a quoted run kept whole. */
function terms(q: string): string[] {
	return q
		.trim()
		.split(/\s+(?=(?:[^"]*"[^"]*")*[^"]*$)/)
		.filter(Boolean);
}

/** One narrowing already applied, and the query without it. */
export type Applied = { label: string; without: string };

const OPERATOR = /^-?(?:from|by|is|after|before):/;
const DATE = /^(?:after|before):/;

const STATES: Record<string, string> = {
	unread: 'Never opened',
	read: 'Opened',
	finished: 'Read to the end',
	unfinished: 'Not read to the end',
};

function reads(term: string): string {
	const at = term.indexOf(':');
	const key = term.slice(0, at);
	const value = term.slice(at + 1).replaceAll('"', '');
	if (key === 'is') return STATES[value] ?? value;
	return key.startsWith('-') ? `not ${value}` : value;
}

/** A date pair as the one period it is, or whichever half of it was given. */
function period(dates: string[]): string {
	const since = dates.find((term) => term.startsWith('after:'))?.slice(6);
	const until = dates.find((term) => term.startsWith('before:'))?.slice(7);
	if (since && until && within(since) === `after:${since} before:${until}`) {
		return volume(since);
	}
	if (since && until) return `${volume(since)} to ${volume(until)}`;
	return since ? `${volume(since)} on` : `up to ${volume(until ?? '')}`;
}

/** Every narrowing the query carries, as words, each with the query that drops it.
 *
 *  The rail cannot offer this: the row you drilled through is the one that stops being in
 *  the list, so once you are inside a year nothing there can take you back out. */
export function applied(view: View): Applied[] {
	const all = terms(view.q);
	const dates = all.filter((term) => DATE.test(term));
	const named = all.filter((term) => OPERATOR.test(term) && !DATE.test(term));
	const words = all.filter((term) => !OPERATOR.test(term));

	const dropping = (some: string[]) => all.filter((term) => !some.includes(term)).join(' ');

	return [
		// A period reads as one thing and comes off as one, however many terms bound it.
		...(dates.length ? [{ label: period(dates), without: dropping(dates) }] : []),
		...named.map((term) => ({ label: reads(term), without: dropping([term]) })),
		// The words come off together: half a phrase is not a search anybody typed.
		...(words.length
			? [{ label: `\u201c${words.join(' ')}\u201d`, without: dropping(words) }]
			: []),
	];
}

/** Whether the query already carries this narrowing. Whole terms, never a substring —
 *  and a period is two of them, so it counts as carried only if both are. */
export function carries(view: View, term: string): boolean {
	const has = new Set(terms(view.q));
	return terms(term).every((each) => has.has(each));
}

/** One narrowing on, or off again if it is already on. One click does both, because a
 *  filter you cannot take off is one you have to retype the query to escape. */
export function toggled(view: View, term: string): string {
	const adding = terms(term);
	const already = terms(view.q);
	if (carries(view, term)) {
		return search(already.filter((each) => !adding.includes(each)).join(' '));
	}
	// A period is one thing however many terms bound it, so picking another replaces the
	// one there rather than stacking a second pair the parser would silently overrule.
	const dated = adding.some((each) => DATE.test(each));
	const kept = dated ? already.filter((each) => !DATE.test(each)) : already;
	return search([...kept, ...adding].join(' '));
}

export function from(title: string): string {
	return `from:${named(title)}`;
}

/** `2026` or `2026-06` as the pair of dates the grammar spells that period with. */
export function within(name: string): string {
	const [year, ordinal] = name.split('-').map(Number);
	if (!year) return name;
	if (!ordinal) return `after:${year} before:${year + 1}`;
	const next = `${year + Math.floor(ordinal / 12)}-${String((ordinal % 12) + 1).padStart(2, '0')}`;
	return `after:${name} before:${next}`;
}

/** `2026` or `2026-06` as the reader's own words for it. The rail labels periods; this
 *  reads them. A year is already its own word. */
export function volume(name: string): string {
	const [year, ordinal] = name.split('-').map(Number);
	if (!year) return name;
	if (!ordinal) return String(year);
	return new Date(Date.UTC(year, ordinal - 1, 1)).toLocaleDateString(undefined, {
		month: 'long',
		year: 'numeric',
		timeZone: 'UTC',
	});
}
