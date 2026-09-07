type Watched = { told: (share: number) => void; of: string };

/** How far a scroller has been taken, 0 to 1. Nothing to scroll is all of it. */
export function progressed(node: HTMLElement, options: Watched) {
	let current = options;
	let queued = false;

	function measure() {
		queued = false;
		const room = node.scrollHeight - node.clientHeight;
		current.told(room > 0 ? Math.min(1, node.scrollTop / room) : 1);
	}

	function later() {
		if (queued) return;
		queued = true;
		requestAnimationFrame(measure);
	}

	// The pane keeps its height and what is in it does not, so both are watched: an image
	// arriving late is the difference between an article that scrolls and one that does not.
	const observer = new ResizeObserver(later);

	function attach() {
		observer.disconnect();
		observer.observe(node);
		for (const child of node.children) observer.observe(child);
	}

	attach();
	node.addEventListener('scroll', later, { passive: true });

	return {
		update(next: Watched) {
			current = next;
			attach();
			later();
		},
		destroy() {
			node.removeEventListener('scroll', later);
			observer.disconnect();
		},
	};
}
