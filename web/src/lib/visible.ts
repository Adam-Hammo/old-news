/** Call back when a node scrolls into view, a little before it actually does. */
export function whenVisible(node: HTMLElement, onVisible: () => void) {
	const observer = new IntersectionObserver(
		(entries) => entries.some((entry) => entry.isIntersecting) && onVisible(),
		{ rootMargin: '600px' },
	);
	observer.observe(node);
	return { destroy: () => observer.disconnect() };
}
