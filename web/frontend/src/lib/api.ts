import type { Meta, Part } from './types';

export async function fetchParts(): Promise<Part[]> {
	const r = await fetch('/api/parts');
	if (!r.ok) throw new Error(`GET /api/parts failed: ${r.status}`);
	return r.json();
}

export async function fetchMeta(): Promise<Meta> {
	const r = await fetch('/api/parts/meta');
	if (!r.ok) throw new Error(`GET /api/parts/meta failed: ${r.status}`);
	return r.json();
}
