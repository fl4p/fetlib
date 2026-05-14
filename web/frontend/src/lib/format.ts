function sig(v: number, n = 3): string {
	if (v === 0) return '0';
	const abs = Math.abs(v);
	const decimals = Math.max(0, n - Math.floor(Math.log10(abs)) - 1);
	return v.toFixed(Math.min(decimals, 6));
}

export function fmtVoltage(v: number | null): string {
	if (v == null) return '';
	return sig(v) + ' V';
}

export function fmtMilliOhm(v: number | null): string {
	if (v == null) return '';
	return sig(v * 1e3) + ' mΩ';
}

export function fmtAmp(v: number | null): string {
	if (v == null) return '';
	return sig(v) + ' A';
}

export function fmtNanoC(v: number | null): string {
	if (v == null) return '';
	return sig(v * 1e9) + ' nC';
}

export function fmtRatio(v: number | null): string {
	if (v == null) return '';
	return v.toFixed(2);
}

export function fmtDate(s: string | null): string {
	return s ?? '';
}
