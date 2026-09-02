import { afterEach, expect, test, vi } from 'vitest';
import { STALE, whenStale } from './stale.ts';

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

function hidden(is: boolean) {
	vi.spyOn(document, 'hidden', 'get').mockReturnValue(is);
}

test('a river left open is asked for again once it has aged out', () => {
	vi.useFakeTimers();
	const again = vi.fn();

	const stop = whenStale(() => true, again);
	vi.advanceTimersByTime(STALE);
	stop();

	expect(again).toHaveBeenCalled();
});

test('one that has not aged out is left alone', () => {
	vi.useFakeTimers();
	const again = vi.fn();

	const stop = whenStale(() => false, again);
	vi.advanceTimersByTime(STALE);
	stop();

	expect(again).not.toHaveBeenCalled();
});

// A tab nobody is looking at is a request nobody asked for.
test('a backgrounded tab asks for nothing', () => {
	vi.useFakeTimers();
	hidden(true);
	const again = vi.fn();

	const stop = whenStale(() => true, again);
	vi.advanceTimersByTime(STALE * 4);
	stop();

	expect(again).not.toHaveBeenCalled();
});

test('coming back to it after a while asks straight away', () => {
	const again = vi.fn();

	const stop = whenStale(() => true, again);
	document.dispatchEvent(new Event('visibilitychange'));
	stop();

	expect(again).toHaveBeenCalledOnce();
});

test('a torn-down clock stops asking', () => {
	vi.useFakeTimers();
	const again = vi.fn();

	whenStale(() => true, again)();
	vi.advanceTimersByTime(STALE * 4);
	document.dispatchEvent(new Event('visibilitychange'));

	expect(again).not.toHaveBeenCalled();
});
