<script lang="ts">
	import type { FilterState, Meta } from './types';
	import { SLIDER_KEYS } from './filters';
	import RangeSlider from './RangeSlider.svelte';
	import { fmtAmp, fmtMilliOhm, fmtNanoC, fmtRatio, fmtVoltage } from './format';

	interface Props {
		meta: Meta;
		state: FilterState;
		filteredCount: number;
		totalCount: number;
		onchange: (state: FilterState) => void;
	}

	let { meta, state, filteredCount, totalCount, onchange }: Props = $props();

	const labels: Record<(typeof SLIDER_KEYS)[number], string> = {
		Vds_max: 'V_DS max',
		Rds_on_max: 'R_DSon max',
		Id: 'I_D',
		Qsw: 'Q_sw',
		Qg: 'Q_g',
		Qrr: 'Q_rr',
		Vsd: 'V_SD',
		QgdQgs_ratio: 'Q_gd / Q_gs'
	};

	const formatters: Record<(typeof SLIDER_KEYS)[number], (v: number) => string> = {
		Vds_max: (v) => fmtVoltage(v),
		Rds_on_max: (v) => fmtMilliOhm(v),
		Id: (v) => fmtAmp(v),
		Qsw: (v) => fmtNanoC(v),
		Qg: (v) => fmtNanoC(v),
		Qrr: (v) => fmtNanoC(v),
		Vsd: (v) => fmtVoltage(v),
		QgdQgs_ratio: (v) => fmtRatio(v)
	};

	function updateRange(key: string, values: [number, number]) {
		onchange({ ...state, ranges: { ...state.ranges, [key]: values } });
	}

	function toggleSet(set: Set<string>, value: string): Set<string> {
		const next = new Set(set);
		if (next.has(value)) next.delete(value);
		else next.add(value);
		return next;
	}

	function toggleMfr(value: string) {
		onchange({ ...state, manufacturers: toggleSet(state.manufacturers, value) });
	}

	function toggleHousing(value: string) {
		onchange({ ...state, housings: toggleSet(state.housings, value) });
	}

	function allMfrs() {
		onchange({ ...state, manufacturers: new Set(meta.manufacturers.map((b) => b.value ?? '')) });
	}

	function noneMfrs() {
		onchange({ ...state, manufacturers: new Set() });
	}

	function allHousings() {
		onchange({ ...state, housings: new Set(meta.housings.map((b) => b.value ?? '')) });
	}

	function noneHousings() {
		onchange({ ...state, housings: new Set() });
	}

	function resetRanges() {
		const ranges: Record<string, [number, number]> = {};
		for (const k of SLIDER_KEYS) {
			const r = meta.ranges[k];
			ranges[k] = r ? [r.min, r.max] : [0, 0];
		}
		onchange({ ...state, ranges });
	}
</script>

<aside>
	<header>
		<div class="count">
			<strong>{filteredCount.toLocaleString()}</strong> / {totalCount.toLocaleString()} parts
		</div>
	</header>

	<section>
		<div class="section-head">
			<h3>Numeric filters</h3>
			<button type="button" onclick={resetRanges}>reset</button>
		</div>
		{#each SLIDER_KEYS as key}
			{@const r = meta.ranges[key]}
			{#if r && r.max > r.min}
				<div class="slider-row">
					<div class="slider-label">{labels[key]}</div>
					<RangeSlider
						min={r.min}
						max={r.max}
						values={state.ranges[key] as [number, number]}
						formatter={formatters[key]}
						onchange={(v) => updateRange(key, v)}
					/>
				</div>
			{/if}
		{/each}
	</section>

	<section>
		<div class="section-head">
			<h3>Manufacturer</h3>
			<span class="actions">
				<button type="button" onclick={allMfrs}>all</button>
				<button type="button" onclick={noneMfrs}>none</button>
			</span>
		</div>
		<ul class="checks">
			{#each meta.manufacturers as b}
				{@const v = b.value ?? ''}
				<li>
					<label>
						<input
							type="checkbox"
							checked={state.manufacturers.has(v)}
							onchange={() => toggleMfr(v)}
						/>
						<span class="lbl">{v || '(N/A)'}</span>
						<span class="cnt">{b.count}</span>
					</label>
				</li>
			{/each}
		</ul>
	</section>

	<section>
		<div class="section-head">
			<h3>Housing</h3>
			<span class="actions">
				<button type="button" onclick={allHousings}>all</button>
				<button type="button" onclick={noneHousings}>none</button>
			</span>
		</div>
		<ul class="checks">
			{#each meta.housings as b}
				{@const v = b.value ?? ''}
				<li>
					<label>
						<input
							type="checkbox"
							checked={state.housings.has(v)}
							onchange={() => toggleHousing(v)}
						/>
						<span class="lbl">{v || '(N/A)'}</span>
						<span class="cnt">{b.count}</span>
					</label>
				</li>
			{/each}
		</ul>
	</section>
</aside>

<style>
	aside {
		width: 300px;
		flex: 0 0 300px;
		border-right: 1px solid #e5e7eb;
		background: #fafafa;
		overflow-y: auto;
		padding: 1rem 0.75rem 2rem;
		font-size: 13px;
		box-sizing: border-box;
	}
	header {
		padding-bottom: 0.5rem;
		margin-bottom: 0.5rem;
		border-bottom: 1px solid #e5e7eb;
	}
	.count {
		font-size: 14px;
	}
	section {
		margin-top: 1rem;
	}
	.section-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 0.25rem;
	}
	.section-head h3 {
		font-size: 13px;
		font-weight: 600;
		margin: 0;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #374151;
	}
	.section-head button,
	.actions button {
		font-size: 11px;
		background: none;
		border: 1px solid #d1d5db;
		border-radius: 3px;
		padding: 1px 6px;
		cursor: pointer;
		color: #4b5563;
		margin-left: 4px;
	}
	.section-head button:hover,
	.actions button:hover {
		background: #f3f4f6;
	}
	.slider-row {
		margin-bottom: 0.5rem;
	}
	.slider-label {
		font-size: 12px;
		color: #4b5563;
		margin-bottom: 2px;
	}
	ul.checks {
		list-style: none;
		padding: 0;
		margin: 0;
		max-height: 220px;
		overflow-y: auto;
		border: 1px solid #e5e7eb;
		border-radius: 3px;
		background: #fff;
	}
	ul.checks li label {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 2px 6px;
		cursor: pointer;
	}
	ul.checks li label:hover {
		background: #f3f4f6;
	}
	.lbl {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cnt {
		color: #6b7280;
		font-variant-numeric: tabular-nums;
		font-size: 11px;
	}
</style>
