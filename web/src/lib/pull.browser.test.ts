import { expect, test, vi } from 'vitest';
import { pull, type Phase } from './pull.ts';

function scroller(scrollTop = 0): HTMLElement {
	const node = document.createElement('div');
	node.style.cssText = 'height: 100px; overflow-y: auto';
	const inner = document.createElement('div');
	inner.style.height = '1000px';
	node.append(inner);
	document.body.append(node);
	node.scrollTop = scrollTop;
	return node;
}

function drag(node: HTMLElement, ...path: number[]) {
	for (const [index, clientY] of path.entries()) {
		const touches = [new Touch({ identifier: 0, target: node, clientX: 0, clientY })];
		const type = index === 0 ? 'touchstart' : 'touchmove';
		node.dispatchEvent(new TouchEvent(type, { touches, cancelable: true, bubbles: true }));
	}
	node.dispatchEvent(new TouchEvent('touchend', { cancelable: true, bubbles: true }));
}

function watched(scrollTop = 0) {
	const node = scroller(scrollTop);
	const refresh = vi.fn(() => Promise.resolve());
	const phases: Phase[] = [];
	pull(node, { pulled: (phase) => phases.push(phase), refresh });
	return { node, refresh, phases };
}

test('a pull past the trigger asks for the river again', async () => {
	const { node, refresh, phases } = watched();

	drag(node, 0, 40, 120, 300);
	await vi.waitFor(() => expect(refresh).toHaveBeenCalledOnce());

	expect(phases).toContain('ready');
	expect(phases.at(-1)).toBe('');
});

test('a pull that stops short of it does not', () => {
	const { node, refresh, phases } = watched();

	drag(node, 0, 12);

	expect(refresh).not.toHaveBeenCalled();
	expect(phases).toEqual(['pulling', '']);
});

// The list has to stay a list: the gesture only means refresh at the very top.
test('a drag from a scrolled list is left to scroll', () => {
	const { node, refresh, phases } = watched(200);

	drag(node, 0, 300);

	expect(refresh).not.toHaveBeenCalled();
	expect(phases).toEqual([]);
	expect(node.style.getPropertyValue('--pull')).toBe('');
});

test('a drag upwards is left to scroll', () => {
	const { node, refresh } = watched();

	drag(node, 300, 100);

	expect(refresh).not.toHaveBeenCalled();
});
