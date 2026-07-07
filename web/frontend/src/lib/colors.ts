import type { Part } from './types';

// macOS Finder tag palette. Index 0 = no tag.
export const TAG_COLORS = [
	null,
	'#FF5C5C', // red
	'#FF9F0A', // orange
	'#FFD60A', // yellow
	'#30D158', // green
	'#0A84FF', // blue
	'#BF5AF2', // purple
	'#8E8E93' // gray
] as const;

export type ColorMap = Record<string, number>;

const STORAGE_KEY = 'mosfet-search.colors';

export function partKey(p: { mfr: string; mpn: string }): string {
	return p.mfr + '|' + p.mpn;
}

export function nextColor(idx: number): number {
	return (idx + 1) % TAG_COLORS.length;
}

export function loadColors(): ColorMap {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return {};
		const parsed = JSON.parse(raw);
		if (parsed && typeof parsed === 'object') {
			const out: ColorMap = {};
			for (const [k, v] of Object.entries(parsed)) {
				if (typeof v === 'number' && v > 0 && v < TAG_COLORS.length) out[k] = v;
			}
			return out;
		}
	} catch {
		/* ignore */
	}
	return {};
}

export function saveColors(c: ColorMap) {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(c));
	} catch {
		/* quota or disabled — ignore */
	}
}

export function cycle(c: ColorMap, p: Part): ColorMap {
	const k = partKey(p);
	const cur = c[k] ?? 0;
	const nxt = nextColor(cur);
	if (nxt === 0) {
		const { [k]: _, ...rest } = c;
		return rest;
	}
	return { ...c, [k]: nxt };
}
