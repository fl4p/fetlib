<script lang="ts">
	import { onMount } from 'svelte';
	import Sidebar from '$lib/Sidebar.svelte';
	import Table from '$lib/Table.svelte';
	import { fetchMeta, fetchParts, fetchSimilar } from '$lib/api';
	import { SLIDER_KEYS, applyFilters, initialFilters, sliderBounds, sortParts } from '$lib/filters';
	import { type ColorMap, cycle, loadColors, saveColors } from '$lib/colors';
	import { type Theme, applyTheme, detectInitialTheme } from '$lib/theme';
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
	let theme = $state<Theme>('light');

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
			theme = detectInitialTheme();
			applyTheme(theme);
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

	function toggleTheme() {
		theme = theme === 'dark' ? 'light' : 'dark';
		applyTheme(theme);
	}

	function clearSimilar() {
		similarMode = null;
		similarError = null;
		if (sortKey === ('score' as SortKey)) sortKey = 'Vds_max';
	}
</script>

<svelte:head>
	<title>FETLIB · power MOSFET parametric search</title>
</svelte:head>

<div class="page">
	<header class="page-header">
		<button
			type="button"
			class="hamburger"
			aria-label="open filters"
			onclick={() => (sidebarOpen = true)}
		>
			≡
		</button>
		<div class="brand">
			<svg class="mark" viewBox="0 0 24 24" aria-hidden="true">
				<g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="square">
					<line x1="1" y1="12" x2="8" y2="12" />
					<line x1="8" y1="7" x2="8" y2="17" />
					<line x1="10" y1="7" x2="10" y2="10" />
					<line x1="10" y1="11" x2="10" y2="13" />
					<line x1="10" y1="14" x2="10" y2="17" />
					<line x1="10" y1="8" x2="16" y2="8" />
					<line x1="16" y1="8" x2="16" y2="1" />
					<line x1="10" y1="16" x2="16" y2="16" />
					<line x1="16" y1="16" x2="16" y2="23" />
					<line x1="10" y1="12" x2="16" y2="12" />
				</g>
				<path d="M 13 10 L 13 14 L 15.5 12 Z" fill="currentColor" />
			</svg>
			<span class="wordmark">FETLIB</span>
			<span class="rule"></span>
			<span class="tagline">power MOSFET parametric search</span>
		</div>
		<div class="header-meta">
			{#if meta && filters}
				<span class="count">
					<span class="num">{sorted.length.toLocaleString()}</span>
					<span class="slash">/</span>
					<span class="num muted">{sourceParts.length.toLocaleString()}</span>
				</span>
			{/if}
			<button
				type="button"
				class="theme-toggle"
				aria-label="toggle dark mode"
				title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
				onclick={toggleTheme}
			>
				{theme === 'dark' ? '☀' : '☾'}
			</button>
		</div>
	</header>

	<main>
		{#if loading}
			<div class="status">
				<span class="blink">▌</span> loading parts library…
			</div>
		{:else if loadError}
			<div class="status error">
				<strong>ERR</strong> · failed to load data: {loadError}
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
				{#if similarMode}
					<div class="similar-banner">
						<span class="bn-label">SIM</span>
						<span class="bn-text">
							similar to <strong>{similarMode.mfr} / {similarMode.mpn}</strong>
							<span class="muted">· {similarMode.parts.length} results</span>
							{#if similarLoading}<span class="muted">· querying…</span>{/if}
						</span>
						<button type="button" onclick={clearSimilar} aria-label="clear similarity">× clear</button>
					</div>
				{/if}
				{#if similarError}
					<div class="similar-banner err">
						<span class="bn-label">ERR</span>
						<span class="bn-text">similarity failed: {similarError}</span>
						<button type="button" onclick={() => (similarError = null)} aria-label="dismiss">×</button>
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
</div>

<style>
	:global(:root) {
		--serif: 'IBM Plex Serif', 'Source Serif Pro', Georgia, 'Times New Roman', serif;
		--mono: 'IBM Plex Mono', 'JetBrains Mono', Menlo, Consolas, monospace;

		--bg: #f1ebde;
		--bg-alt: #e8e0cf;
		--bg-paper: #f5efe2;
		--bg-hover: #ddd2bc;
		--bg-row-hover: rgba(42, 60, 100, 0.07);
		--bg-th: #1a1714;
		--bg-th-sorted: #2a3c64;
		--bg-trunc: #efe1c2;
		--bg-banner: #e2dac6;
		--bg-banner-err: #f0d4c4;
		--bg-input: #fbf6e9;

		--text: #1a1714;
		--text-strong: #0d0c0a;
		--text-muted: #786a55;
		--text-label: #3a3024;
		--text-on-dark: #f5efe2;
		--text-accent: #2a3c64;
		--text-accent-strong: #142348;
		--text-err: #82221b;

		--border: #1a1714;
		--border-thin: rgba(26, 23, 20, 0.18);
		--border-strong: #1a1714;
		--border-row: rgba(26, 23, 20, 0.1);
		--border-accent: #2a3c64;
		--border-err: #82221b;
		--border-trunc: #c79b2e;

		color-scheme: light;
	}
	:global(:root.dark) {
		--bg: #15130d;
		--bg-alt: #1c1a14;
		--bg-paper: #1a1812;
		--bg-hover: #2d2820;
		--bg-row-hover: rgba(255, 178, 71, 0.08);
		--bg-th: #ffb347;
		--bg-th-sorted: rgba(255, 178, 71, 0.2);
		--bg-trunc: #2a2418;
		--bg-banner: #221d12;
		--bg-banner-err: #2a1410;
		--bg-input: #1a1812;

		--text: #d99544;
		--text-strong: #ffb347;
		--text-muted: #816138;
		--text-label: #b88444;
		--text-on-dark: #15130d;
		--text-accent: #ffb347;
		--text-accent-strong: #ffd089;
		--text-err: #ff7755;

		--border: #4a3624;
		--border-thin: rgba(255, 178, 71, 0.18);
		--border-strong: #6a4f30;
		--border-row: rgba(255, 178, 71, 0.1);
		--border-accent: #ffb347;
		--border-err: #ff7755;
		--border-trunc: #6a4f30;

		color-scheme: dark;
	}
	:global(html, body) {
		margin: 0;
		padding: 0;
		font-family: var(--serif);
		font-feature-settings: 'kern', 'liga';
		color: var(--text);
		background: var(--bg);
	}
	:global(:root.dark body) {
		text-shadow: 0 0 8px rgba(255, 178, 71, 0.18);
	}

	.page {
		display: flex;
		flex-direction: column;
		height: 100vh;
		overflow: hidden;
	}
	main {
		display: flex;
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}

	.page-header {
		display: flex;
		align-items: stretch;
		background: var(--bg-paper);
		border-bottom: 3px double var(--border);
		padding: 0 18px;
		height: 56px;
		flex-shrink: 0;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 14px;
		flex: 1;
		min-width: 0;
	}
	.mark {
		width: 26px;
		height: 26px;
		color: var(--text-strong);
		flex-shrink: 0;
	}
	.wordmark {
		font-family: var(--serif);
		font-weight: 700;
		font-size: 22px;
		letter-spacing: 0.1em;
		color: var(--text-strong);
		line-height: 1;
	}
	.brand .rule {
		flex: 0 0 1px;
		align-self: stretch;
		background: var(--border-thin);
		margin: 14px 0;
	}
	.tagline {
		font-family: var(--serif);
		font-style: italic;
		font-size: 13px;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.header-meta {
		display: flex;
		align-items: center;
		gap: 14px;
		padding-left: 16px;
	}
	.count {
		font-family: var(--mono);
		font-size: 12px;
		letter-spacing: 0.02em;
		color: var(--text);
	}
	.count .num {
		font-weight: 600;
	}
	.count .num.muted {
		color: var(--text-muted);
		font-weight: 400;
	}
	.count .slash {
		color: var(--text-muted);
		margin: 0 3px;
	}
	.theme-toggle {
		width: 32px;
		height: 32px;
		border-radius: 0;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		cursor: pointer;
		font-size: 16px;
		line-height: 1;
		padding: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-family: inherit;
	}
	.theme-toggle:hover {
		background: var(--text);
		color: var(--text-on-dark);
	}
	.hamburger {
		display: none;
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text);
		font-family: var(--serif);
		font-size: 22px;
		line-height: 1;
		padding: 0;
		width: 32px;
		height: 32px;
		margin-right: 12px;
		align-self: center;
		cursor: pointer;
	}
	.hamburger:hover {
		background: var(--text);
		color: var(--text-on-dark);
	}
	.backdrop {
		display: none;
	}
	@media (max-width: 768px) {
		.hamburger {
			display: inline-flex;
			align-items: center;
			justify-content: center;
		}
		.tagline,
		.brand .rule {
			display: none;
		}
		.backdrop {
			display: block;
			position: fixed;
			inset: 0;
			background: rgba(0, 0, 0, 0.5);
			border: none;
			padding: 0;
			margin: 0;
			z-index: 15;
			cursor: pointer;
		}
		.page-header {
			padding: 0 12px;
			height: 52px;
		}
		.header-meta {
			gap: 10px;
			padding-left: 10px;
		}
		.wordmark {
			font-size: 18px;
		}
	}

	.main-col {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
		background: var(--bg-paper);
	}
	.similar-banner {
		background: var(--bg-banner);
		border-bottom: 1px solid var(--border);
		padding: 8px 14px;
		font-family: var(--serif);
		font-size: 13px;
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.similar-banner .bn-label {
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.18em;
		padding: 2px 6px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		flex-shrink: 0;
	}
	.similar-banner .bn-text {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.similar-banner strong {
		font-family: var(--mono);
		font-weight: 600;
	}
	.similar-banner .muted {
		color: var(--text-muted);
	}
	.similar-banner.err {
		background: var(--bg-banner-err);
		border-bottom-color: var(--border-err);
		color: var(--text-err);
	}
	.similar-banner.err .bn-label {
		border-color: var(--border-err);
		color: var(--text-err);
		background: var(--bg);
	}
	.similar-banner button {
		font-family: var(--mono);
		font-size: 11px;
		letter-spacing: 0.06em;
		background: transparent;
		border: 1px solid var(--border);
		border-radius: 0;
		padding: 3px 10px;
		cursor: pointer;
		color: var(--text);
	}
	.similar-banner button:hover {
		background: var(--text);
		color: var(--text-on-dark);
	}
	.similar-banner.err button {
		border-color: var(--border-err);
		color: var(--text-err);
	}
	.similar-banner.err button:hover {
		background: var(--text-err);
		color: var(--bg);
	}

	.status {
		padding: 2rem;
		font-family: var(--mono);
		font-size: 13px;
		letter-spacing: 0.02em;
		color: var(--text);
	}
	.status.error {
		color: var(--text-err);
	}
	.status strong {
		font-weight: 600;
		letter-spacing: 0.1em;
		padding: 2px 6px;
		border: 1px solid currentColor;
		margin-right: 6px;
	}
	.blink {
		display: inline-block;
		animation: blink 1.1s steps(2, end) infinite;
		color: var(--text-strong);
		margin-right: 6px;
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}
	.hint {
		margin-top: 0.5rem;
		color: var(--text-muted);
		font-size: 12px;
	}
</style>
