/** Every view is a query into one column, so every link is built from the same two keys. */
export type View = { section: string; archive: boolean };

function query(view: View): string {
	// `encodeURIComponent`, not `URLSearchParams`: that spells a space `+`, and the rest
	// of the app spells it `%20`. Two spellings of one view is two URLs for one screen.
	const pairs = [
		view.section ? `section=${encodeURIComponent(view.section)}` : '',
		view.archive ? 'archive=1' : '',
	].filter(Boolean);
	return pairs.length ? `?${pairs.join('&')}` : '';
}

export function river(view: View): string {
	return `/${query(view)}`;
}

export function section(name: string, view: View): string {
	return river({ ...view, section: name });
}

export function item(id: string, view: View): string {
	return `/item/${id}${query(view)}`;
}

export function archive(view: View, into: boolean): string {
	return river({ ...view, archive: into });
}
