import { goto, type AfterNavigate } from '$app/navigation';
import { page } from '$app/state';

/** Note on the entry just pushed where it came from, which only the entry can be trusted to know. */
export function remember({ from, to, type }: AfterNavigate) {
	if (!from || !to || type === 'popstate' || type === 'enter') return;
	const behind = from.url.pathname + from.url.search;
	const here = to.url.pathname + to.url.search;
	// The stamp below is a navigation too, from this entry to itself.
	if (behind === here || page.state.behind === behind) return;
	void goto(here, {
		state: { behind },
		shallow: true,
		replace: true,
	});
}

/** Back through history when that is where the link goes, rather than pushing the list again. */
export function back(event: MouseEvent & { currentTarget: HTMLAnchorElement }) {
	if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
	if (page.state.behind !== event.currentTarget.getAttribute('href')) return;
	event.preventDefault();
	history.back();
}
