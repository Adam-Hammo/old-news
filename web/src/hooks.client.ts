import type { HandleClientError } from '@sveltejs/kit/hooks';
import { report } from '#lib/report.ts';

// Only the unexpected reach here: an `error()` this client threw is handled and has a page
// of its own. Anything else is a fault nothing in the browser otherwise writes down.
export const handleError: HandleClientError = ({ error, event }) => {
	report('error', String((error as Error)?.stack ?? error), event.url.pathname);
};
