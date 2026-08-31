const CLOCK = new Intl.DateTimeFormat(undefined, {
	hour: '2-digit',
	minute: '2-digit',
	hour12: false,
});
const SHORT = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' });
const DAY = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'long' });
const MASTHEAD = new Intl.DateTimeFormat(undefined, {
	weekday: 'long',
	day: 'numeric',
	month: 'long',
});

/** A clock time while it is still today, a date once it is not. */
export function stamp(when: string | null, now = Date.now()): string {
	if (!when) return '';
	const at = new Date(when);

	if (at.toDateString() !== new Date(now).toDateString()) return SHORT.format(at);
	// A full stop, not a colon: the masthead and the bylines are set in small caps and a
	// colon sits badly against them.
	return CLOCK.format(at).replace(':', '.');
}

/** The article's own dateline: `31 August, 07.52`. */
export function dateline(when: string | null): string {
	if (!when) return '';
	const at = new Date(when);
	return `${DAY.format(at)}, ${CLOCK.format(at).replace(':', '.')}`;
}

/** The paper's own date, which is today's — the way a masthead has always carried it. */
export function today(now = Date.now()): string {
	return MASTHEAD.format(new Date(now));
}
