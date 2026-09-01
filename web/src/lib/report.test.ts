import { expect, test, vi } from 'vitest';

const sent = vi.hoisted(() => [] as unknown[]);
vi.mock('#lib/api/client.ts', () => ({ sendReport: (r: unknown) => sent.push(r) }));

const { REPEAT_WINDOW, report } = await import('./report.ts');

// What is remembered to spot a repeat outlives one test, so each of these reports about
// its own article rather than about a shared one.
test('the same fault twice over is reported once', () => {
	sent.length = 0;

	report('error', 'boom', '/item/a', 1000);
	report('error', 'boom', '/item/a', 1000 + REPEAT_WINDOW - 1);

	expect(sent).toHaveLength(1);
});

test('the same fault again later is worth knowing about', () => {
	sent.length = 0;

	report('error', 'boom', '/item/b', 1000);
	report('error', 'boom', '/item/b', 1000 + REPEAT_WINDOW + 1);

	expect(sent).toHaveLength(2);
});

// `handleError` must not throw, and this runs inside it.
test('a browser that cannot answer what it is does not make a second failure', () => {
	sent.length = 0;

	expect(() => report('error', 'boom', '/item/c', 9000)).not.toThrow();
	expect(sent).toHaveLength(1);
});

// Two faults in a row are two faults, however close together.
test('a different fault is never swallowed', () => {
	sent.length = 0;

	report('error', 'boom', '/item/d', 1000);
	report('error', 'boom', '/item/e', 1001);
	report('mismatch', 'boom', '/item/e', 1002);

	expect(sent).toHaveLength(3);
});
