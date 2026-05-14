import { SLIDER_KEYS, sliderBounds } from './filters';
import type { FilterState, Meta, SortDir, SortKey } from './types';

const EPS = 1e-9;
function near(a: number, b: number): boolean {
	return Math.abs(a - b) < EPS * (1 + Math.abs(b));
}

export interface ParsedUrlState {
	search: string;
	ranges: Record<string, [number, number]>;
	manufacturers: Set<string> | null;
	housings: Set<string> | null;
	similar: { mfr: string; mpn: string } | null;
	sortKey: SortKey | null;
	sortDir: SortDir | null;
}

const DEFAULT_SORT_KEY: SortKey = 'Vds_max';
const DEFAULT_SORT_DIR: SortDir = 'asc';

export function serializeState(
	state: FilterState,
	similar: { mfr: string; mpn: string } | null,
	sortKey: SortKey,
	sortDir: SortDir,
	meta: Meta
): string {
	const p = new URLSearchParams();
	if (state.search) p.set('q', state.search);

	for (const k of SLIDER_KEYS) {
		const r = meta.ranges[k];
		if (!r) continue;
		const b = sliderBounds(r);
		const cur = state.ranges[k];
		if (!cur) continue;
		if (!near(cur[0], b.min)) p.set(`r.${k}.lo`, cur[0].toString());
		if (!near(cur[1], b.max)) p.set(`r.${k}.hi`, cur[1].toString());
	}

	const allMfr = new Set(meta.manufacturers.map((b) => b.value ?? ''));
	if (!setsEqual(state.manufacturers, allMfr)) {
		for (const m of [...state.manufacturers].sort()) p.append('mfr', m);
	}

	const allPkg = new Set(meta.housings.map((b) => b.value ?? ''));
	if (!setsEqual(state.housings, allPkg)) {
		for (const h of [...state.housings].sort()) p.append('pkg', h);
	}

	if (similar) {
		p.set('sim.mfr', similar.mfr);
		p.set('sim.mpn', similar.mpn);
	}

	if (sortKey !== DEFAULT_SORT_KEY || sortDir !== DEFAULT_SORT_DIR) {
		p.set('sort', `${String(sortKey)}:${sortDir}`);
	}

	return p.toString();
}

export function parseState(hash: string): ParsedUrlState | null {
	const trimmed = hash.replace(/^#/, '');
	if (!trimmed) return null;
	const p = new URLSearchParams(trimmed);

	const search = p.get('q') ?? '';

	const ranges: Record<string, [number, number]> = {};
	for (const k of SLIDER_KEYS) {
		const loStr = p.get(`r.${k}.lo`);
		const hiStr = p.get(`r.${k}.hi`);
		if (loStr === null && hiStr === null) continue;
		const lo = loStr === null ? Number.NEGATIVE_INFINITY : parseFloat(loStr);
		const hi = hiStr === null ? Number.POSITIVE_INFINITY : parseFloat(hiStr);
		if (Number.isFinite(lo) || Number.isFinite(hi)) ranges[k] = [lo, hi];
	}

	const mfrValues = p.getAll('mfr');
	const pkgValues = p.getAll('pkg');

	const simMfr = p.get('sim.mfr');
	const simMpn = p.get('sim.mpn');
	const similar = simMfr && simMpn ? { mfr: simMfr, mpn: simMpn } : null;

	let sortKey: SortKey | null = null;
	let sortDir: SortDir | null = null;
	const sortStr = p.get('sort');
	if (sortStr) {
		const [k, d] = sortStr.split(':');
		if (k) sortKey = k as SortKey;
		if (d === 'asc' || d === 'desc') sortDir = d;
	}

	return {
		search,
		ranges,
		manufacturers: mfrValues.length > 0 ? new Set(mfrValues) : null,
		housings: pkgValues.length > 0 ? new Set(pkgValues) : null,
		similar,
		sortKey,
		sortDir
	};
}

export function applyParsedToFilters(
	parsed: ParsedUrlState,
	base: FilterState,
	meta: Meta
): FilterState {
	const out: FilterState = {
		search: parsed.search,
		ranges: { ...base.ranges },
		manufacturers: parsed.manufacturers ?? base.manufacturers,
		housings: parsed.housings ?? base.housings
	};
	for (const k of SLIDER_KEYS) {
		const r = meta.ranges[k];
		if (!r) continue;
		const b = sliderBounds(r);
		const p = parsed.ranges[k];
		if (!p) continue;
		const lo = Number.isFinite(p[0]) ? Math.max(b.min, Math.min(p[0], b.max)) : b.min;
		const hi = Number.isFinite(p[1]) ? Math.max(b.min, Math.min(p[1], b.max)) : b.max;
		if (lo <= hi) out.ranges[k] = [lo, hi];
	}
	return out;
}

function setsEqual(a: Set<string>, b: Set<string>): boolean {
	if (a.size !== b.size) return false;
	for (const v of a) if (!b.has(v)) return false;
	return true;
}
