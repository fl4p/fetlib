<script lang="ts">
	import type { FilterState, Meta } from './types';
	import { SLIDER_KEYS, sliderBounds } from './filters';
	import RangeSlider from './RangeSlider.svelte';
	import {
		fmtAmp,
		fmtFomNc,
		fmtFomPf,
		fmtMilliOhm,
		fmtNanoC,
		fmtRatio,
		fmtVoltage
	} from './format';

	interface Props {
		meta: Meta;
		state: FilterState;
		filteredCount: number;
		totalCount: number;
		onchange: (state: FilterState) => void;
		onSliderPending?: (key: string, pending: boolean) => void;
		open?: boolean;
		onclose?: () => void;
	}

	let {
		meta,
		state,
		filteredCount,
		totalCount,
		onchange,
		onSliderPending,
		open = true,
		onclose
	}: Props = $props();

	const labels: Record<(typeof SLIDER_KEYS)[number], string> = {
		Vds_max: 'V_DS max',
		Rds_on_max: 'R_DSon max',
		Id: 'I_D',
		Qsw: 'Q_sw',
		Qg: 'Q_g',
		Qrr: 'Q_rr',
		Vsd: 'V_SD',
		QgdQgs_ratio: 'Q_gd / Q_gs',
		FoM: 'FoM (R·Qg)',
		FoMqsw: 'FoM_sw (R·Qsw)',
		FoMqrr: 'FoM_rr (R·Qrr)',
		FoMcoss: 'FoM_oss (R·Coss)'
	};

	const formatters: Record<(typeof SLIDER_KEYS)[number], (v: number) => string> = {
		Vds_max: (v) => fmtVoltage(v),
		Rds_on_max: (v) => fmtMilliOhm(v),
		Id: (v) => fmtAmp(v),
		Qsw: (v) => fmtNanoC(v),
		Qg: (v) => fmtNanoC(v),
		Qrr: (v) => fmtNanoC(v),
		Vsd: (v) => fmtVoltage(v),
		QgdQgs_ratio: (v) => fmtRatio(v),
		FoM: (v) => fmtFomNc(v),
		FoMqsw: (v) => fmtFomNc(v),
		FoMqrr: (v) => fmtFomNc(v),
		FoMcoss: (v) => fmtFomPf(v)
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

<aside class:open>
	<header>
		<div class="count">
			<strong>{filteredCount.toLocaleString()}</strong> / {totalCount.toLocaleString()} parts
		</div>
		{#if onclose}
			<button type="button" class="close-btn" aria-label="close filters" onclick={onclose}>×</button>
		{/if}
	</header>

	<section>
		<input
			type="search"
			class="search"
			placeholder="search Mfr / MPN / housing / values · * wildcard"
			value={state.search}
			oninput={(e) => onchange({ ...state, search: (e.currentTarget as HTMLInputElement).value })}
		/>
	</section>

	<section>
		<div class="section-head">
			<h3>Numeric filters</h3>
			<button type="button" onclick={resetRanges}>reset</button>
		</div>
		{#each SLIDER_KEYS as key}
			{@const r = meta.ranges[key]}
			{@const b = r ? sliderBounds(r) : null}
			{#if r && b && b.max > b.min}
				<div class="slider-row">
					<div class="slider-label">{labels[key]}</div>
					<RangeSlider
						min={b.min}
						max={b.max}
						values={state.ranges[key] as [number, number]}
						formatter={formatters[key]}
						log
						onchange={(v) => updateRange(key, v)}
						onpending={(p) => onSliderPending?.(key, p)}
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
		width: 280px;
		flex: 0 0 280px;
		border-right: 1px solid var(--border);
		background: var(--bg-alt);
		color: var(--text);
		overflow-y: auto;
		padding: 1.1rem 1rem 2rem;
		font-family: var(--serif);
		font-size: 13px;
		box-sizing: border-box;
		line-height: 1.4;
	}
	header {
		padding-bottom: 0.5rem;
		margin-bottom: 0.75rem;
		border-bottom: 3px double var(--border);
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.count {
		font-family: var(--mono);
		font-size: 11px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.count strong {
		color: var(--text-strong);
		font-weight: 600;
		font-size: 13px;
	}
	.close-btn {
		display: none;
		font-family: var(--serif);
		font-size: 22px;
		line-height: 1;
		padding: 0 6px;
		background: transparent;
		border: 1px solid var(--border);
		border-radius: 0;
		cursor: pointer;
		color: var(--text);
	}
	.close-btn:hover {
		background: var(--text);
		color: var(--text-on-dark);
	}
	@media (max-width: 768px) {
		aside {
			position: fixed;
			top: 0;
			left: 0;
			height: 100vh;
			width: 86%;
			max-width: 320px;
			z-index: 20;
			transform: translateX(-100%);
			transition: transform 200ms ease-out;
			box-shadow: 6px 0 0 var(--border-thin);
			padding-top: 1rem;
		}
		aside.open {
			transform: translateX(0);
		}
		.close-btn {
			display: inline-block;
		}
		.search {
			font-size: 16px;
		}
	}
	section {
		margin-top: 1.1rem;
	}
	.section-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 0.45rem;
		padding-bottom: 0.25rem;
		border-bottom: 1px solid var(--border-thin);
	}
	.section-head h3 {
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 600;
		margin: 0;
		text-transform: uppercase;
		letter-spacing: 0.18em;
		color: var(--text-strong);
	}
	.section-head button,
	.actions button {
		font-family: var(--mono);
		font-size: 9.5px;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		background: transparent;
		border: 1px solid var(--border-thin);
		border-radius: 0;
		padding: 1px 6px;
		cursor: pointer;
		color: var(--text-muted);
		margin-left: 4px;
	}
	.section-head button:hover,
	.actions button:hover {
		background: var(--text);
		color: var(--text-on-dark);
		border-color: var(--text);
	}
	.search {
		width: 100%;
		box-sizing: border-box;
		padding: 8px 10px;
		font-family: var(--mono);
		font-size: 12px;
		border: 1px solid var(--border);
		border-radius: 0;
		background: var(--bg-input);
		color: var(--text);
	}
	.search::placeholder {
		color: var(--text-muted);
		font-style: italic;
		font-family: var(--serif);
	}
	.search:focus {
		outline: none;
		border-color: var(--text);
		box-shadow: inset 0 0 0 1px var(--text);
	}
	.slider-row {
		margin-bottom: 0.5rem;
	}
	.slider-label {
		font-family: var(--mono);
		font-size: 11px;
		font-weight: bold;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-label);
		margin-bottom: 4px;
	}
	ul.checks {
		list-style: none;
		padding: 0;
		margin: 0;
		max-height: 220px;
		overflow-y: auto;
		border: 1px solid var(--border);
		border-radius: 0;
		background: var(--bg-input);
		font-family: var(--serif);
	}
	ul.checks li label {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 3px 8px;
		cursor: pointer;
	}
	ul.checks li label:hover {
		background: var(--bg-hover);
	}
	ul.checks input[type='checkbox'] {
		accent-color: var(--border-accent);
		margin: 0;
	}
	.lbl {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cnt {
		color: var(--text-muted);
		font-family: var(--mono);
		font-size: 10px;
		font-variant-numeric: tabular-nums;
	}
</style>
