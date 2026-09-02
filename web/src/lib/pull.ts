/** How far a pull has got, and what it will do if it is let go here. */
export type Phase = '' | 'pulling' | 'ready' | 'refreshing';

type Pull = { pulled: (phase: Phase) => void; refresh: () => Promise<void> };

const TRIGGER = 64;
const LIMIT = 96;

/** Drag down at the top of a scroller to ask for it again. Touch only: a desk has the timer. */
export function pull(node: HTMLElement, options: Pull) {
	let current = options;
	let start = 0;
	let distance = 0;
	let dragging = false;

	function move(to: number) {
		distance = to;
		node.style.setProperty('--pull', `${to}px`);
		current.pulled(to === 0 ? '' : to >= TRIGGER ? 'ready' : 'pulling');
	}

	function down(event: TouchEvent) {
		dragging = event.touches.length === 1 && node.scrollTop <= 0;
		start = event.touches[0].clientY;
	}

	function drag(event: TouchEvent) {
		if (!dragging) return;
		const travelled = event.touches[0].clientY - start;
		// Upwards, or away from the top: an ordinary scroll, and the browser can have it.
		if (travelled <= 0 || node.scrollTop > 0) {
			if (distance) move(0);
			return;
		}
		event.preventDefault();
		// Asymptotic, so the pull gets heavier and the list never leaves the frame.
		move(LIMIT * (1 - Math.exp(-travelled / LIMIT)));
	}

	async function up() {
		if (!dragging) return;
		dragging = false;
		if (distance < TRIGGER) return move(0);

		current.pulled('refreshing');
		node.style.setProperty('--pull', `${TRIGGER}px`);
		try {
			await current.refresh();
		} finally {
			move(0);
		}
	}

	node.addEventListener('touchstart', down, { passive: true });
	node.addEventListener('touchmove', drag, { passive: false });
	node.addEventListener('touchend', up);
	node.addEventListener('touchcancel', up);

	return {
		update: (next: Pull) => (current = next),
		destroy: () => {
			node.removeEventListener('touchstart', down);
			node.removeEventListener('touchmove', drag);
			node.removeEventListener('touchend', up);
			node.removeEventListener('touchcancel', up);
		},
	};
}
