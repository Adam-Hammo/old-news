/** How far a scroller has been taken, 0 to 1. Nothing to scroll is all of it. */
export function watching(node: HTMLElement, told: (share: number) => void): () => void {
	let queued = false;

	function measure() {
		queued = false;
		const room = node.scrollHeight - node.clientHeight;
		told(room > 0 ? Math.min(1, node.scrollTop / room) : 1);
	}

	function later() {
		if (queued) return;
		queued = true;
		requestAnimationFrame(measure);
	}

	// The pane keeps its height and what is in it does not, so both are watched: an image
	// arriving late is the difference between an article that scrolls and one that does not.
	const observer = new ResizeObserver(later);
	observer.observe(node);
	for (const child of node.children) observer.observe(child);

	node.addEventListener('scroll', later, { passive: true });
	later();

	return () => {
		node.removeEventListener('scroll', later);
		observer.disconnect();
	};
}
