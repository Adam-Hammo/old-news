import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from 'vitest';

// The design as assertions, the way tests/unit/test_architecture.py does for the Python
// side. Each of these describes something that otherwise goes wrong quietly: a colour
// that only exists in one scheme, and a component that stopped asking for a token.

const SRC = path.resolve(import.meta.dirname);
const STYLESHEET = path.join(SRC, 'app.css');
const OFFLINE = path.resolve(SRC, '..', 'static', 'offline.html');

// The lookbehind is what keeps `&#183;` from reading as a colour: an HTML entity is
// digits after a `#` too, and this file is the only thing that can tell them apart.
const COLOUR =
	/(?<!&)#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b|\brgba?\(|\bhsla?\(|\bokl(ab|ch)\(|\bcolor-mix\(/;

const stylesheet = () => fs.readFileSync(STYLESHEET, 'utf8');

function components(): string[] {
	const found: string[] = [];
	const walk = (dir: string) => {
		for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
			const full = path.join(dir, entry.name);
			if (entry.isDirectory()) walk(full);
			else if (entry.name.endsWith('.svelte')) found.push(full);
		}
	};
	walk(SRC);
	return found;
}

function block(pattern: RegExp): string {
	const found = stylesheet().match(pattern);
	expect(found, `${pattern} is missing from app.css`).not.toBeNull();
	return found![1];
}

/** The tokens in one block whose value is a colour. The rest are type and rhythm. */
function palette(declarations: string): Set<string> {
	return new Set(
		[...declarations.matchAll(/--([\w-]+):\s*([^;]+);/g)]
			.filter(([, , value]) => COLOUR.test(value))
			.map(([, name]) => name),
	);
}

const LIGHT = /^:root \{\n([\s\S]*?)\n\}/m;
const DARK = /@media \(prefers-color-scheme: dark\) \{\n\t:root \{\n([\s\S]*?)\n\t\}/m;

test('every colour a component paints comes from a token', () => {
	const offenders = components().filter((file) => COLOUR.test(fs.readFileSync(file, 'utf8')));

	expect(offenders.map((f) => path.relative(SRC, f))).toEqual([]);
});

test('the system decides the scheme, so the root has to say it renders both', () => {
	expect(block(LIGHT)).toContain('color-scheme: light dark');
});

test('no colour is defined for only one of the two schemes', () => {
	const light = palette(block(LIGHT));
	const dark = palette(block(DARK));

	// A token missing from dark keeps its light value there and is invisible; one missing
	// from light is undefined until the system happens to be dark.
	expect(
		[...dark].filter((name) => !light.has(name)),
		'declared only in dark',
	).toEqual([]);
	expect(
		[...light].filter((name) => !dark.has(name)),
		'declared only in light',
	).toEqual([]);
});

test('the offline page follows the system too, since it is what shows when nothing else can', () => {
	const html = fs.readFileSync(OFFLINE, 'utf8');

	expect(html).toContain('color-scheme: light dark');
	expect(html).toContain('prefers-color-scheme: dark');
});
