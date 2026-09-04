import { expect, test } from 'vitest';
import { marked } from './snippet.ts';

const OPEN = '\x02';
const CLOSE = '\x03';

test('a fragment with nothing marked is one run of prose', () => {
	expect(marked('just some words')).toEqual([{ text: 'just some words', hit: false }]);
});

test('what matched comes back as its own run', () => {
	expect(marked(`the ${OPEN}density${CLOSE} of it`)).toEqual([
		{ text: 'the ', hit: false },
		{ text: 'density', hit: true },
		{ text: ' of it', hit: false },
	]);
});

test('every match in the fragment is marked, not just the first', () => {
	const runs = marked(`${OPEN}a${CLOSE} and ${OPEN}b${CLOSE}`);

	expect(runs.filter((run) => run.hit).map((run) => run.text)).toEqual(['a', 'b']);
});

// A fragment is cut to length, so the closing marker can be the part that was cut off.
test('a match left open by the cut is still a match', () => {
	expect(marked(`the ${OPEN}dens`)).toEqual([
		{ text: 'the ', hit: false },
		{ text: 'dens', hit: true },
	]);
});

test('an empty run is not a run', () => {
	expect(marked(`${OPEN}density${CLOSE}`)).toEqual([{ text: 'density', hit: true }]);
});

test('nothing at all is no runs', () => {
	expect(marked('')).toEqual([]);
});

// The fragment is a publisher's prose, so markup in it is text and stays text.
test('markup in the fragment is not a marker', () => {
	expect(marked('a <b>bold</b> claim')).toEqual([{ text: 'a <b>bold</b> claim', hit: false }]);
});
