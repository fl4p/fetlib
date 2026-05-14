<script lang="ts">
	import { onMount } from 'svelte';
	import Sidebar from '$lib/Sidebar.svelte';
	import Table from '$lib/Table.svelte';
	import { fetchMeta, fetchParts } from '$lib/api';
	import { applyFilters, initialFilters, sortParts } from '$lib/filters';
	import type { FilterState, Meta, Part, SortDir, SortKey } from '$lib/types';

	let parts = $state<Part[]>([]);
	let meta = $state<Meta | null>(null);
	let filters = $state<FilterState | null>(null);
	let sortKey = $state<SortKey>('Vds_max');
	let sortDir = $state<SortDir>('asc');
	let loadError = $state<string | null>(null);
	let loading = $state(true);

	onMount(async () => {
		try {
			const [p, m] = await Promise.all([fetchParts(), fetchMeta()]);
			parts = p;
			meta = m;
			filters = initialFilters(m);
		} catch (e) {
			loadError = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	});

	const filtered = $derived.by(() => {
		if (!meta || !filters) return [];
		return applyFilters(parts, filters, meta);
	});

	const sorted = $derived(sortParts(filtered, sortKey, sortDir));

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
			totalCount={parts.length}
			onchange={setFilters}
		/>
		<Table rows={sorted} {sortKey} {sortDir} onsort={onSort} />
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
