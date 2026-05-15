import { format } from 'd3-format';

const d3sig = format('.3~r');

function num(v: number): string {
	return d3sig(v).replace('−', '-').replace(/\.$/, '');
}

export function fmtVoltage(v: number | null): string {
	if (v == null) return '';
	return num(v) + ' V';
}

export function fmtMilliOhm(v: number | null): string {
	if (v == null) return '';
	return num(v * 1e3) + ' mΩ';
}

export function fmtAmp(v: number | null): string {
	if (v == null) return '';
	return num(v) + ' A';
}

export function fmtNanoC(v: number | null): string {
	if (v == null) return '';
	return num(v * 1e9) + ' nC';
}

export function fmtRatio(v: number | null): string {
	if (v == null) return '';
	return num(v);
}

export function fmtFomNc(v: number | null): string {
	if (v == null) return '';
	return num(v) + ' mΩ·nC';
}

export function fmtFomPf(v: number | null): string {
	if (v == null) return '';
	return num(v) + ' mΩ·pF';
}

export function fmtDate(s: string | null): string {
	return s ?? '';
}
