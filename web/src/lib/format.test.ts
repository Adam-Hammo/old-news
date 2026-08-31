import { describe, expect, test } from 'vitest';
import { dateline, stamp } from './format.ts';

const NOW = Date.parse('2026-08-31T12:00:00Z');
const HOUR = 3_600_000;
const DAY = 24 * HOUR;

const at = (ms: number) => new Date(NOW - ms).toISOString();

describe('stamp', () => {
	test('an item with no publisher date shows nothing rather than a placeholder', () => {
		expect(stamp(null, NOW)).toBe('');
	});

	test('a clock time while it is still today', () => {
		expect(stamp(at(4 * HOUR), NOW)).toMatch(/^\d{2}\.\d{2}$/);
	});

	// The byline is set in small caps and a colon sits badly against them.
	test('separated by a full stop, not a colon', () => {
		expect(stamp(at(4 * HOUR), NOW)).not.toContain(':');
	});

	test('a date once it is not today', () => {
		expect(stamp(at(3 * DAY), NOW)).not.toMatch(/^\d{2}\.\d{2}$/);
	});
});

describe('dateline', () => {
	test('nothing for an item with no date', () => {
		expect(dateline(null)).toBe('');
	});

	test('the article carries a day and a time, which the river row does not', () => {
		const rendered = dateline('2026-08-30T07:52:00Z');

		expect(rendered).toMatch(/30/);
		expect(rendered).toMatch(/\d{2}\.\d{2}$/);
	});
});
