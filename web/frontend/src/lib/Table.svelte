<script lang="ts">
	import type { Part, SortDir, SortKey } from './types';
	import { fmtAmp, fmtDate, fmtMilliOhm, fmtNanoC, fmtRatio, fmtVoltage } from './format';

	interface Props {
		rows: Part[];
		sortKey: SortKey;
		sortDir: SortDir;
		onsort: (key: SortKey) => void;
	}

	let { rows, sortKey, sortDir, onsort }: Props = $props();

	interface Col {
		key: SortKey;
		label: string;
		fmt: (p: Part) => string;
		num?: boolean;
	}

	const columns: Col[] = [
		{ key: 'mfr', label: 'Mfr', fmt: (p) => p.mfr },
		{ key: 'mpn', label: 'MPN', fmt: (p) => p.mpn },
		{ key: 'substrate', label: 'Substrate', fmt: (p) => p.substrate },
		{ key: 'housing', label: 'Housing', fmt: (p) => p.housing ?? '' },
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
		{ key: 'date', label: 'Date', fmt: (p) => fmtDate(p.date) }
	];

	function arrow(key: SortKey): string {
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
						<button type="button" onclick={() => onsort(col.key)}>
							{col.label}{arrow(col.key)}
						</button>
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each visible as p (p.mfr + '|' + p.mpn)}
				<tr>
					{#each columns as col}
						<td class:num={col.num}>{col.fmt(p)}</td>
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
		background: #fff;
	}
	table {
		border-collapse: collapse;
		width: 100%;
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	thead th {
		position: sticky;
		top: 0;
		background: #f3f4f6;
		border-bottom: 1px solid #d1d5db;
		text-align: left;
		font-weight: 600;
		color: #1f2937;
		z-index: 1;
		padding: 0;
		white-space: nowrap;
	}
	thead th button {
		background: none;
		border: none;
		padding: 6px 8px;
		font: inherit;
		font-weight: inherit;
		cursor: pointer;
		color: inherit;
		width: 100%;
		text-align: left;
	}
	thead th.num button {
		text-align: right;
	}
	thead th.sorted {
		background: #dbeafe;
	}
	thead th button:hover {
		background: #e5e7eb;
	}
	td {
		padding: 3px 8px;
		border-bottom: 1px solid #f1f5f9;
		white-space: nowrap;
	}
	td.num {
		text-align: right;
	}
	tbody tr:hover {
		background: #f9fafb;
	}
	.trunc {
		padding: 8px 12px;
		font-size: 12px;
		color: #6b7280;
		background: #fffbeb;
		border-top: 1px solid #fde68a;
	}
</style>
