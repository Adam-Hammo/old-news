/** The settings screen's pages. Each loads only what it shows. */
export const TABS = [
	{ id: 'feeds', label: 'Feeds' },
	{ id: 'polling', label: 'Polling' },
	{ id: 'publishers', label: 'Publishers' },
	{ id: 'filters', label: 'Filters' },
	{ id: 'config', label: 'Config' },
] as const;

export type Tab = (typeof TABS)[number]['id'];

/** Whichever page the URL asks for. Anything else is the one you get by arriving. */
export function tabbed(asked: string | null): Tab {
	return TABS.some((tab) => tab.id === asked) ? (asked as Tab) : 'feeds';
}

export function href(tab: Tab): string {
	return tab === 'feeds' ? '/settings' : `/settings?tab=${tab}`;
}
