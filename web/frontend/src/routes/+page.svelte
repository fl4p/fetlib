<script lang="ts">
	import { onMount } from 'svelte';
	import Sidebar from '$lib/Sidebar.svelte';
	import Table from '$lib/Table.svelte';
	import { fetchMeta, fetchParts, fetchSimilar } from '$lib/api';
	import { SLIDER_KEYS, applyFilters, initialFilters, sliderBounds, sortParts } from '$lib/filters';
	import { type ColorMap, cycle, loadColors, saveColors } from '$lib/colors';
	import type { FilterState, Meta, Part, SortDir, SortKey } from '$lib/types';
	import { applyParsedToFilters, parseState, serializeState } from '$lib/url';

	const STORAGE_KEY = 'mosfet-search.ranges';

	let parts = $state<Part[]>([]);
	let meta = $state<Meta | null>(null);
	let filters = $state<FilterState | null>(null);
	let sortKey = $state<SortKey>('Vds_max');
	let sortDir = $state<SortDir>('asc');
	let loadError = $state<string | null>(null);
	let loading = $state(true);
	let pendingSliders = $state(new Set<string>());
	let similarMode = $state<{ mfr: string; mpn: string; parts: Part[] } | null>(null);
	let similarLoading = $state(false);
	let similarError = $state<string | null>(null);
	let colors = $state<ColorMap>({});
	let sidebarOpen = $state(false);

	function loadStoredRanges(): Record<string, [number, number]> | null {
		try {
			const raw = localStorage.getItem(STORAGE_KEY);
			if (!raw) return null;
			const parsed = JSON.parse(raw);
			return parsed && typeof parsed === 'object' ? parsed : null;
		} catch {
			return null;
		}
	}

	function saveRanges(ranges: Record<string, [number, number]>) {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(ranges));
		} catch {
			/* quota or disabled — ignore */
		}
	}

	function buildInitialFilters(m: Meta): FilterState {
		const init = initialFilters(m);
		const stored = loadStoredRanges();
		if (!stored) return init;
		for (const k of SLIDER_KEYS) {
			const v = stored[k];
			const r = m.ranges[k];
			if (
				Array.isArray(v) &&
				v.length === 2 &&
				typeof v[0] === 'number' &&
				typeof v[1] === 'number' &&
				r
			) {
				const b = sliderBounds(r);
				const lo = Math.max(b.min, Math.min(v[0], b.max));
				const hi = Math.max(b.min, Math.min(v[1], b.max));
				if (lo <= hi) init.ranges[k] = [lo, hi];
			}
		}
		return init;
	}

	let suppressUrlWrite = false;
	let lastWrittenHash = '';

	onMount(async () => {
		try {
			colors = loadColors();
			const [p, m] = await Promise.all([fetchParts(), fetchMeta()]);
			parts = p;
			meta = m;

			let base = buildInitialFilters(m);
			const parsed = parseState(window.location.hash);
			let initialSimilar: { mfr: string; mpn: string } | null = null;
			if (parsed) {
				base = applyParsedToFilters(parsed, base, m);
				if (parsed.sortKey) sortKey = parsed.sortKey;
				if (parsed.sortDir) sortDir = parsed.sortDir;
				initialSimilar = parsed.similar;
			}
			filters = base;

			if (initialSimilar) {
				await runSimilar(initialSimilar.mfr, initialSimilar.mpn);
			}

			window.addEventListener('hashchange', handleHashChange);
		} catch (e) {
			loadError = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	$effect(() => {
		if (!meta || !filters || suppressUrlWrite) return;
		const query = serializeState(filters, similarMode, sortKey, sortDir, meta);
		const target = query ? '#' + query : window.location.pathname + window.location.search;
		const next = query ? target : window.location.pathname + window.location.search;
		if (next === lastWrittenHash) return;
		lastWrittenHash = next;
		const url = query
			? window.location.pathname + window.location.search + target
			: window.location.pathname + window.location.search;
		history.replaceState(null, '', url);
	});

	function handleHashChange() {
		if (!meta) return;
		const parsed = parseState(window.location.hash);
		suppressUrlWrite = true;
		try {
			let next = buildInitialFilters(meta);
			if (parsed) {
				next = applyParsedToFilters(parsed, next, meta);
				if (parsed.sortKey) sortKey = parsed.sortKey;
				if (parsed.sortDir) sortDir = parsed.sortDir;
			} else {
				sortKey = 'Vds_max';
				sortDir = 'asc';
			}
			filters = next;
			const wantSim = parsed?.similar ?? null;
			const haveSim = similarMode ? { mfr: similarMode.mfr, mpn: similarMode.mpn } : null;
			if (wantSim && (!haveSim || haveSim.mfr !== wantSim.mfr || haveSim.mpn !== wantSim.mpn)) {
				runSimilar(wantSim.mfr, wantSim.mpn);
			} else if (!wantSim && haveSim) {
				similarMode = null;
				similarError = null;
			}
		} finally {
			suppressUrlWrite = false;
		}
	}

	const sourceParts = $derived(similarMode ? similarMode.parts : parts);

	const filtered = $derived.by(() => {
		if (!meta || !filters) return [];
		return applyFilters(sourceParts, filters, meta);
	});

	const sorted = $derived(sortParts(filtered, sortKey, sortDir));
	const tablePending = $derived(pendingSliders.size > 0);

	function onSort(key: SortKey) {
		if (key === sortKey) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDir = 'asc';
		}
	}

	function setFilters(s: FilterState) {
		filters = s;
		saveRanges(s.ranges);
	}

	function onSliderPending(key: string, p: boolean) {
		const next = new Set(pendingSliders);
		if (p) next.add(key);
		else next.delete(key);
		pendingSliders = next;
	}

	async function runSimilar(mfr: string, mpn: string) {
		similarLoading = true;
		similarError = null;
		try {
			const results = await fetchSimilar(mfr, mpn, 30);
			similarMode = {
				mfr,
				mpn,
				parts: results.map((r) => ({ ...r.part, score: r.score }))
			};
			sortKey = 'score' as SortKey;
			sortDir = 'asc';
		} catch (e) {
			similarError = e instanceof Error ? e.message : String(e);
		} finally {
			similarLoading = false;
		}
	}

	function onFindSimilar(p: Part) {
		return runSimilar(p.mfr, p.mpn);
	}

	function onColorClick(p: Part) {
		colors = cycle(colors, p);
		saveColors(colors);
	}

	function clearSimilar() {
		similarMode = null;
		similarError = null;
		if (sortKey === ('score' as SortKey)) sortKey = 'Vds_max';
	}
</script>

<svelte:head>
	<title>MOSFET parametric search</title>
</svelte:head>

<main>
	{#if loading}
		<div class="status">Loading parts…</div>
	{:else if loadError}
		<div class="status error">
			Failed to load data: {loadError}
			<div class="hint">Make sure the backend is running on :8000 (see web/README.md).</div>
		</div>
	{:else if meta && filters}
		<Sidebar
			{meta}
			state={filters}
			filteredCount={sorted.length}
			totalCount={sourceParts.length}
			onchange={setFilters}
			{onSliderPending}
			open={sidebarOpen}
			onclose={() => (sidebarOpen = false)}
		/>
		{#if sidebarOpen}
			<button
				type="button"
				class="backdrop"
				aria-label="close filters"
				onclick={() => (sidebarOpen = false)}
			></button>
		{/if}
		<div class="main-col">
			<button
				type="button"
				class="hamburger"
				aria-label="open filters"
				onclick={() => (sidebarOpen = true)}
			>
				<span class="bars">≡</span>
				<span class="label">Filters</span>
				<span class="count-pill"
					>{sorted.length.toLocaleString()} / {sourceParts.length.toLocaleString()}</span
				>
			</button>
			{#if similarMode}
				<div class="similar-banner">
					<span>
						Similar to <strong>{similarMode.mfr} / {similarMode.mpn}</strong>
						· {similarMode.parts.length} results
						{#if similarLoading}<em>loading…</em>{/if}
					</span>
					<button type="button" onclick={clearSimilar}>× clear</button>
				</div>
			{/if}
			{#if similarError}
				<div class="similar-banner err">
					Similarity failed: {similarError}
					<button type="button" onclick={() => (similarError = null)}>×</button>
				</div>
			{/if}
			<Table
				rows={sorted}
				{sortKey}
				{sortDir}
				onsort={onSort}
				pending={tablePending}
				showScore={!!similarMode}
				onfindSimilar={onFindSimilar}
				{colors}
				oncolorClick={onColorClick}
			/>
		</div>
	{/if}
</main>

<style>
	:global(html, body) {
		margin: 0;
		padding: 0;
		font-family:
			ui-sans-serif,
			system-ui,
			-apple-system,
			Segoe UI,
			Roboto,
			sans-serif;
		color: #111827;
		background: #fff;
	}
	main {
		display: flex;
		height: 100vh;
		overflow: hidden;
	}
	.hamburger {
		display: none;
	}
	.backdrop {
		display: none;
	}
	@media (max-width: 768px) {
		.hamburger {
			display: flex;
			align-items: center;
			gap: 10px;
			padding: 10px 14px;
			background: #fff;
			border: none;
			border-bottom: 1px solid #e5e7eb;
			font-size: 15px;
			font-family: inherit;
			cursor: pointer;
			text-align: left;
		}
		.hamburger .bars {
			font-size: 22px;
			line-height: 1;
		}
		.hamburger .count-pill {
			margin-left: auto;
			font-size: 12px;
			color: #6b7280;
			background: #f3f4f6;
			padding: 2px 8px;
			border-radius: 10px;
		}
		.backdrop {
			display: block;
			position: fixed;
			inset: 0;
			background: rgba(0, 0, 0, 0.4);
			border: none;
			padding: 0;
			margin: 0;
			z-index: 15;
			cursor: pointer;
		}
	}
	.main-col {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.similar-banner {
		background: #eef2ff;
		border-bottom: 1px solid #c7d2fe;
		padding: 6px 12px;
		font-size: 13px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.similar-banner.err {
		background: #fef2f2;
		border-bottom-color: #fecaca;
		color: #991b1b;
	}
	.similar-banner button {
		font-size: 12px;
		background: transparent;
		border: 1px solid #c7d2fe;
		border-radius: 3px;
		padding: 1px 8px;
		cursor: pointer;
		color: #1d4ed8;
	}
	.similar-banner button:hover {
		background: #c7d2fe;
	}
	.similar-banner em {
		color: #6b7280;
		font-style: normal;
		margin-left: 6px;
	}
	.status {
		padding: 2rem;
		font-size: 14px;
	}
	.status.error {
		color: #b91c1c;
	}
	.hint {
		margin-top: 0.5rem;
		color: #6b7280;
		font-size: 13px;
	}
</style>
