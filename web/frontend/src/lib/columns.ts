import {
	fmtAmp,
	fmtDate,
	fmtFomNc,
	fmtFomPf,
	fmtMilliOhm,
	fmtNanoC,
	fmtRatio,
	fmtVoltage
} from './format';
import type { Part } from './types';

export interface ColumnDef {
	key: string;
	label: string;
	fmt: (p: Part) => string;
	num?: boolean;
	mpnLink?: boolean;
}

export const COLUMNS: ColumnDef[] = [
	{ key: 'mfr', label: 'Mfr', fmt: (p) => p.mfr },
	{ key: 'mpn', label: 'MPN', fmt: (p) => p.mpn, mpnLink: true },
	{ key: 'substrate', label: 'Tech', fmt: (p) => p.substrate },
	{ key: 'housing', label: 'House', fmt: (p) => p.housing ?? '' },
	{ key: 'Vds_max', label: 'V_DS', fmt: (p) => fmtVoltage(p.Vds_max), num: true },
	{ key: 'Rds_on_max', label: 'R_DSon', fmt: (p) => fmtMilliOhm(p.Rds_on_max), num: true },
	{ key: 'Id', label: 'I_D', fmt: (p) => fmtAmp(p.Id), num: true },
	{ key: 'Qsw', label: 'Q_sw', fmt: (p) => fmtNanoC(p.Qsw), num: true },
	{ key: 'Qg', label: 'Q_g', fmt: (p) => fmtNanoC(p.Qg), num: true },
	{ key: 'Qrr', label: 'Q_rr', fmt: (p) => fmtNanoC(p.Qrr), num: true },
	{ key: 'Vsd', label: 'V_SD', fmt: (p) => fmtVoltage(p.Vsd), num: true },
	{ key: 'V_pl', label: 'V_pl', fmt: (p) => fmtVoltage(p.V_pl), num: true },
	{ key: 'Vgs_th', label: 'V_GS(th)', fmt: (p) => fmtVoltage(p.Vgs_th), num: true },
	{ key: 'QgdQgs_ratio', label: 'Q_gd/Q_gs', fmt: (p) => fmtRatio(p.QgdQgs_ratio), num: true },
	{ key: 'FoM', label: 'FoM', fmt: (p) => fmtFomNc(p.FoM), num: true },
	{ key: 'FoMqsw', label: 'FoM_sw', fmt: (p) => fmtFomNc(p.FoMqsw), num: true },
	{ key: 'FoMqrr', label: 'FoM_rr', fmt: (p) => fmtFomNc(p.FoMqrr), num: true },
	{ key: 'FoMcoss', label: 'FoM_oss', fmt: (p) => fmtFomPf(p.FoMcoss), num: true },
	{ key: 'date', label: 'Date', fmt: (p) => fmtDate(p.date) }
];

const STORAGE_KEY = 'mosfet-search.columns';

export type ColumnVisibility = Record<string, boolean>;

export function loadVisibility(): ColumnVisibility {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) {
			const parsed = JSON.parse(raw);
			if (parsed && typeof parsed === 'object') return parsed;
		}
	} catch {
		/* ignore */
	}
	return {};
}

export function saveVisibility(v: ColumnVisibility) {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(v));
	} catch {
		/* ignore */
	}
}

export function isVisible(v: ColumnVisibility, key: string): boolean {
	return v[key] !== false;
}
