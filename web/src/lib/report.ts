import { sendReport } from '#lib/api/client.ts';

// One fault can surface several times as a navigation unwinds, and a fault that repeats
// would otherwise fill the log with the same line.
export const REPEAT_WINDOW = 5_000;

let shown = Date.now();
let last = { signature: '', at: 0 };

if (typeof document !== 'undefined') {
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'visible') shown = Date.now();
	});
}

/** iOS suspends the home-screen app in a way it does not suspend a tab. */
function display(): string {
	const standalone = typeof matchMedia === 'function' && matchMedia('(display-mode: standalone)');
	return standalone && standalone.matches ? 'standalone' : 'browser';
}

/** Say what went wrong. Nothing else in the browser keeps a record of it. */
export function report(kind: string, message: string, url: string, now = Date.now()): void {
	const signature = `${kind} ${message} ${url}`;
	if (signature === last.signature && now - last.at < REPEAT_WINDOW) return;
	last = { signature, at: now };

	try {
		sendReport({ kind, message, url, display: display(), since_visible: now - shown });
	} catch {
		// `handleError` must not throw, so the report cannot become the second failure.
	}
}
