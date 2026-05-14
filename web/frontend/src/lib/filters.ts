import type { FilterState, Meta, Part, SortDir, SortKey } from './types';
import { fmtAmp, fmtMilliOhm, fmtNanoC, fmtRatio, fmtVoltage } from './format';

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

export function sliderBounds(r: { min: number; max: number; slider_max?: number | null }): {
	min: number;
	max: number;
} {
	return { min: r.min, max: r.slider_max ?? r.max };
}

export function initialFilters(meta: Meta): FilterState {
	const ranges: Record<string, [number, number]> = {};
	for (const k of SLIDER_KEYS) {
		const r = meta.ranges[k];
		const b = r ? sliderBounds(r) : { min: 0, max: 0 };
		ranges[k] = [b.min, b.max];
	}
	return {
		ranges,
		manufacturers: new Set(meta.manufacturers.map((b) => b.value ?? '')),
		housings: new Set(meta.housings.map((b) => b.value ?? '')),
		search: ''
	};
}

const haystackCache = new WeakMap<Part, string>();

function haystack(p: Part): string {
	const cached = haystackCache.get(p);
	if (cached !== undefined) return cached;
	const h = [
		p.mfr,
		p.mpn,
		p.housing ?? '',
		p.substrate,
		fmtVoltage(p.Vds_max),
		fmtMilliOhm(p.Rds_on_max),
		fmtAmp(p.Id),
		fmtNanoC(p.Qsw),
		fmtNanoC(p.Qg),
		fmtNanoC(p.Qrr),
		fmtVoltage(p.Vsd),
		fmtVoltage(p.V_pl),
		fmtVoltage(p.Vgs_th),
		fmtRatio(p.QgdQgs_ratio),
		p.date ?? ''
	].join(' ');
	haystackCache.set(p, h);
	return h;
}

function compileSearch(term: string): RegExp[] | null {
	const tokens = term.trim().split(/\s+/).filter(Boolean);
	if (tokens.length === 0) return null;
	return tokens.map((tok) => {
		const escaped = tok.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
		const re = escaped.replace(/\*/g, '.*');
		return new RegExp(re, 'i');
	});
}

function nearEq(a: number, b: number): boolean {
	return Math.abs(a - b) < EPSILON * (1 + Math.abs(b));
}

export function applyFilters(parts: Part[], state: FilterState, meta: Meta): Part[] {
	const patterns = compileSearch(state.search);
	return parts.filter((p) => {
		if (!state.manufacturers.has(p.mfr)) return false;
		if (!state.housings.has(p.housing ?? '')) return false;

		if (patterns) {
			const h = haystack(p);
			for (const re of patterns) if (!re.test(h)) return false;
		}

		for (const k of SLIDER_KEYS) {
			const range = state.ranges[k];
			const full = meta.ranges[k];
			if (!range || !full) continue;
			const b = sliderBounds(full);
			const lowerFull = nearEq(range[0], b.min);
			const upperFull = nearEq(range[1], b.max);
			const v = p[k];
			if (v == null) {
				if (!(lowerFull && upperFull)) return false;
				continue;
			}
			if (v < range[0] - EPSILON) return false;
			if (v > range[1] + EPSILON && !upperFull) return false;
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
