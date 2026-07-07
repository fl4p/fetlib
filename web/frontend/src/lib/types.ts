export interface Part {
	mfr: string;
	mpn: string;
	substrate: string;
	housing: string | null;
	Vds_max: number | null;
	Rds_on_max: number | null;
	Id: number | null;
	Qsw: number | null;
	Qg: number | null;
	Qrr: number | null;
	Vsd: number | null;
	V_pl: number | null;
	Vgs_th: number | null;
	QgdQgs_ratio: number | null;
	FoM: number | null;
	FoMqsw: number | null;
	FoMqrr: number | null;
	FoMcoss: number | null;
	date: string | null;
	extras?: Record<string, number>;
	score?: number | null;
}

export interface SimilarResult {
	score: number;
	part: Part;
}

export interface Bucket {
	value: string | null;
	count: number;
}

export interface Range {
	min: number;
	max: number;
	slider_max?: number | null;
}

export interface Meta {
	total: number;
	manufacturers: Bucket[];
	housings: Bucket[];
	substrates: Bucket[];
	ranges: Record<string, Range>;
}

export type NumericKey =
	| 'Vds_max'
	| 'Rds_on_max'
	| 'Id'
	| 'Qsw'
	| 'Qg'
	| 'Qrr'
	| 'Vsd'
	| 'V_pl'
	| 'Vgs_th'
	| 'QgdQgs_ratio'
	| 'FoM'
	| 'FoMqsw'
	| 'FoMqrr'
	| 'FoMcoss';

export type SortKey = keyof Part;
export type SortDir = 'asc' | 'desc';

export interface FilterState {
	ranges: Record<string, [number, number]>;
	manufacturers: Set<string>;
	housings: Set<string>;
	search: string;
}
