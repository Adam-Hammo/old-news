// A feed is polled no oftener than every five minutes, so nothing is gained by asking
// sooner than that.
export const STALE = 5 * 60 * 1000;
const CHECK = 60 * 1000;

/** Call back while `due` says what is on screen has aged out. The check also runs on the
 *  way back to the tab, which a throttled timer cannot be trusted to have done. */
export function whenStale(due: () => boolean, onStale: () => void) {
	const tick = () => !document.hidden && due() && onStale();

	const timer = setInterval(tick, CHECK);
	document.addEventListener('visibilitychange', tick);
	return () => {
		clearInterval(timer);
		document.removeEventListener('visibilitychange', tick);
	};
}
