export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'mosfet-search.theme';

export function detectInitialTheme(): Theme {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved === 'light' || saved === 'dark') return saved;
	} catch {
		/* ignore */
	}
	return 'light';
}

export function applyTheme(theme: Theme) {
	if (typeof document === 'undefined') return;
	document.documentElement.classList.toggle('dark', theme === 'dark');
	try {
		localStorage.setItem(STORAGE_KEY, theme);
	} catch {
		/* ignore */
	}
}
