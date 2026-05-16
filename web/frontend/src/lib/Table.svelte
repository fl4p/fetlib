<script lang="ts">
	import type { Part, SortDir, SortKey } from './types';
	import { COLUMNS, isVisible, type ColumnDef, type ColumnVisibility } from './columns';
	import { TAG_COLORS, partKey, type ColorMap } from './colors';

	interface Props {
		rows: Part[];
		sortKey: SortKey;
		sortDir: SortDir;
		onsort: (key: SortKey) => void;
		pending?: boolean;
		showScore?: boolean;
		onfindSimilar?: (p: Part) => void;
		oninfo?: (p: Part) => void;
		colors?: ColorMap;
		oncolorClick?: (p: Part) => void;
		visibleColumns?: ColumnVisibility;
	}

	let {
		rows,
		sortKey,
		sortDir,
		onsort,
		pending = false,
		showScore = false,
		onfindSimilar,
		oninfo,
		colors = {},
		oncolorClick,
		visibleColumns = {}
	}: Props = $props();

	function datasheetHref(p: Part): string {
		return `/api/datasheet?mfr=${encodeURIComponent(p.mfr)}&mpn=${encodeURIComponent(p.mpn)}`;
	}

	const scoreCol: ColumnDef = {
		key: 'score',
		label: 'Score',
		fmt: (p) => (p.score == null ? '' : p.score.toFixed(2)),
		num: true
	};

	const columns = $derived<ColumnDef[]>(
		(showScore ? [scoreCol, ...COLUMNS] : COLUMNS).filter(
			(c) => c.key === 'score' || isVisible(visibleColumns, c.key)
		)
	);

	function arrow(key: string): string {
		if (key !== sortKey) return '';
		return sortDir === 'asc' ? ' ▲' : ' ▼';
	}

	const MAX_ROWS = 2000;
	const visible = $derived(rows.slice(0, MAX_ROWS));
	const truncated = $derived(rows.length > MAX_ROWS);
</script>

<div class="table-wrap">
	<table>
		<thead>
			<tr>
				{#each columns as col}
					<th class:num={col.num} class:sorted={sortKey === col.key}>
						<button type="button" onclick={() => onsort(col.key as SortKey)}>
							{col.label}{arrow(col.key)}
						</button>
					</th>
				{/each}
			</tr>
		</thead>
		<tbody class:pending>
			{#each visible as p (p.mfr + '|' + p.mpn)}
				<tr>
					{#each columns as col}
						<td class:num={col.num}>
							{#if col.mpnLink}
								<a href={datasheetHref(p)} target="_blank" rel="noopener">{col.fmt(p)}</a>
								{#if oninfo}
									<button
										type="button"
										class="info-btn"
										title="More info"
										aria-label="show part details"
										onclick={() => oninfo?.(p)}
									>ⓘ</button>
								{/if}
								{#if oncolorClick}
									{@const idx = colors[partKey(p)] ?? 0}
									{@const fill = TAG_COLORS[idx]}
									<button
										type="button"
										class="tag-btn"
										class:tagged={fill !== null}
										style:background={fill ?? 'transparent'}
										title={fill ? 'Cycle / clear tag' : 'Tag this part'}
										aria-label="cycle tag color"
										onclick={() => oncolorClick?.(p)}
									></button>
								{/if}
								{#if onfindSimilar}
									<button
										type="button"
										class="sim-btn"
										title="Find similar parts"
										onclick={() => onfindSimilar?.(p)}
									>≈</button>
								{/if}
							{:else}
								{col.fmt(p)}
							{/if}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
	{#if truncated}
		<div class="trunc">
			Showing first {MAX_ROWS.toLocaleString()} of {rows.length.toLocaleString()} matches. Tighten filters to see more.
		</div>
	{/if}
</div>

<style>
	.table-wrap {
		flex: 1;
		overflow: auto;
		background: var(--bg-paper);
		color: var(--text);
	}
	table {
		border-collapse: collapse;
		width: 100%;
		font-family: var(--mono);
		font-size: 11.5px;
		font-variant-numeric: tabular-nums;
	}
	thead th {
		position: sticky;
		top: 0;
		background: var(--bg-th);
		color: var(--text-on-dark);
		border-bottom: 2px solid var(--bg-th);
		text-align: left;
		font-family: var(--mono);
		font-weight: 600;
		font-size: 10px;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		z-index: 1;
		padding: 0;
		white-space: nowrap;
	}
	thead th button {
		background: none;
		border: none;
		padding: 9px 10px;
		font: inherit;
		font-weight: inherit;
		letter-spacing: inherit;
		text-transform: inherit;
		cursor: pointer;
		color: inherit;
		width: 100%;
		text-align: left;
	}
	thead th.num button {
		text-align: right;
	}
	thead th.sorted {
		background: var(--bg-th-sorted);
	}
	:global(:root.dark) thead th {
		color: var(--text-on-dark);
	}
	:global(:root.dark) thead th.sorted {
		background: rgba(255, 178, 71, 0.85);
	}
	thead th button:hover {
		background: rgba(255, 255, 255, 0.1);
	}
	td {
		padding: 4px 10px;
		border-bottom: 1px solid var(--border-row);
		white-space: nowrap;
	}
	td.num {
		text-align: right;
	}
	tbody tr:nth-child(even) {
		background: var(--bg-row-hover);
	}
	tbody tr:hover {
		background: var(--bg-hover);
	}
	tbody.pending {
		opacity: 0.5;
		transition: opacity 80ms ease-in;
	}
	tbody {
		transition: opacity 120ms ease-out;
	}
	td a {
		color: var(--text-accent);
		text-decoration: none;
		font-weight: 500;
	}
	td a:hover {
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.sim-btn {
		margin-left: 6px;
		padding: 1px 5px;
		font-family: var(--serif);
		font-size: 14px;
		line-height: 1;
		color: var(--text-muted);
		background: transparent;
		border: 1px solid transparent;
		border-radius: 0;
		cursor: pointer;
	}
	tbody tr:hover .sim-btn {
		color: var(--text);
	}
	.sim-btn:hover {
		border-color: var(--border-thin);
	}
	.info-btn {
		margin-left: 6px;
		padding: 1px 4px;
		font-family: var(--serif);
		font-size: 12px;
		line-height: 1;
		color: var(--text-muted);
		background: transparent;
		border: 1px solid transparent;
		border-radius: 0;
		cursor: pointer;
	}
	tbody tr:hover .info-btn {
		color: var(--text);
	}
	.info-btn:hover {
		border-color: var(--border-thin);
	}
	.tag-btn {
		display: inline-block;
		width: 11px;
		height: 11px;
		margin-left: 5px;
		padding: 0;
		border-radius: 50%;
		border: 1px solid var(--border);
		background: transparent;
		cursor: pointer;
		vertical-align: middle;
	}
	.tag-btn.tagged {
		border-color: rgba(0, 0, 0, 0.35);
	}
	.tag-btn:hover {
		box-shadow: 0 0 0 2px var(--border-thin);
	}
	@media (max-width: 768px) {
		table {
			font-size: 12px;
		}
		td {
			padding: 7px 10px;
		}
		thead th button {
			padding: 10px 10px;
		}
		.sim-btn {
			font-size: 16px;
			padding: 2px 8px;
			margin-left: 8px;
		}
		.info-btn {
			font-size: 15px;
			padding: 2px 7px;
			margin-left: 8px;
		}
		.tag-btn {
			width: 14px;
			height: 14px;
			margin-left: 8px;
		}
	}
	.trunc {
		padding: 10px 14px;
		font-family: var(--mono);
		font-size: 11px;
		letter-spacing: 0.05em;
		color: var(--text);
		background: var(--bg-trunc);
		border-top: 1px solid var(--border-trunc);
	}
</style>
