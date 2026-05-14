import type { FilterState, Meta, Part, SortDir, SortKey } from './types';

export const SLIDER_KEYS = [
	'Vds_max',
	'Rds_on_max',
	'Id',
	'Qsw',
	'Qg',
	'Qrr',
	'Vsd',
	'QgdQgs_ratio'
] as const;

const EPSILON = 1e-9;

export function initialFilters(meta: Meta): FilterState {
	const ranges: Record<string, [number, number]> = {};
	for (const k of SLIDER_KEYS) {
		const r = meta.ranges[k];
		ranges[k] = r ? [r.min, r.max] : [0, 0];
	}
	return {
		ranges,
		manufacturers: new Set(meta.manufacturers.map((b) => b.value ?? '')),
		housings: new Set(meta.housings.map((b) => b.value ?? ''))
	};
}

function isFullRange(current: [number, number], full: { min: number; max: number }): boolean {
	return (
		Math.abs(current[0] - full.min) < EPSILON * (1 + Math.abs(full.min)) &&
		Math.abs(current[1] - full.max) < EPSILON * (1 + Math.abs(full.max))
	);
}

export function applyFilters(parts: Part[], state: FilterState, meta: Meta): Part[] {
	return parts.filter((p) => {
		if (!state.manufacturers.has(p.mfr)) return false;
		if (!state.housings.has(p.housing ?? '')) return false;

		for (const k of SLIDER_KEYS) {
			const range = state.ranges[k];
			const full = meta.ranges[k];
			if (!range || !full) continue;
			const v = p[k];
			if (v == null) {
				if (!isFullRange(range, full)) return false;
				continue;
			}
			if (v < range[0] - EPSILON || v > range[1] + EPSILON) return false;
		}
		return true;
	});
}

export function sortParts(parts: Part[], key: SortKey, dir: SortDir): Part[] {
	const mult = dir === 'asc' ? 1 : -1;
	const arr = parts.slice();
	arr.sort((a, b) => {
		const av = a[key];
		const bv = b[key];
		const aNull = av == null;
		const bNull = bv == null;
		if (aNull && bNull) return 0;
		if (aNull) return 1;
		if (bNull) return -1;
		if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * mult;
		return String(av).localeCompare(String(bv)) * mult;
	});
	return arr;
}
