<script lang="ts">
	import type { Part } from './types';
	import { COLUMNS } from './columns';
	import {
		fmtAmp,
		fmtMilliOhm,
		fmtNanoC,
		fmtNanoS,
		fmtOhm,
		fmtPicoF,
		fmtVoltage
	} from './format';
	import { cubicOut } from 'svelte/easing';
	import { fade } from 'svelte/transition';
	import type { TransitionConfig } from 'svelte/transition';

	interface PropRow {
		key: string;
		label: string;
		fmt: (p: Part) => string;
	}

	function extra(key: string, label: string, fmt: (v: number) => string): PropRow {
		return {
			key,
			label,
			fmt: (p) => {
				const v = p.extras?.[key];
				return v == null ? '' : fmt(v);
			}
		};
	}

	const COL_BY_KEY: Record<string, (typeof COLUMNS)[number]> = Object.fromEntries(
		COLUMNS.map((c) => [c.key, c])
	);

	function col(key: string): PropRow {
		const c = COL_BY_KEY[key];
		return { key, label: c.label, fmt: c.fmt };
	}

	const GROUPS: { label: string; rows: PropRow[] }[] = [
		{
			label: 'Identification',
			rows: [col('mfr'), col('mpn'), col('substrate'), col('housing'), col('date')]
		},
		{
			label: 'Maximum Ratings',
			rows: [col('Vds_max'), col('Id'), extra('ID_25', 'I_D @25°C', fmtAmp)]
		},
		{
			label: 'Static',
			rows: [
				col('Rds_on_max'),
				extra('Rds_on_10v_max', 'R_DSon @10V', fmtMilliOhm),
				col('Vgs_th'),
				extra('Vgs_th_min', 'V_GS(th) min', fmtVoltage)
			]
		},
		{
			label: 'Gate Charge',
			rows: [
				col('Qg'),
				extra('Qg_typ', 'Q_g typ', fmtNanoC),
				extra('Qg_max', 'Q_g max', fmtNanoC),
				extra('Qgs', 'Q_gs', fmtNanoC),
				extra('Qgd', 'Q_gd', fmtNanoC),
				extra('Qgs2', 'Q_gs2', fmtNanoC),
				extra('Qg_th', 'Q_g(th)', fmtNanoC),
				extra('Qg_sync', 'Q_g(sync)', fmtNanoC),
				col('Qsw'),
				col('V_pl'),
				col('QgdQgs_ratio')
			]
		},
		{
			label: 'Switching Times',
			rows: [extra('tRise', 't_r', fmtNanoS), extra('tFall', 't_f', fmtNanoS)]
		},
		{
			label: 'Capacitances',
			rows: [extra('Coss', 'C_oss', fmtPicoF)]
		},
		{
			label: 'Body Diode',
			rows: [col('Vsd'), col('Qrr'), extra('trr', 't_rr', fmtNanoS)]
		},
		{
			label: 'Gate Resistance',
			rows: [extra('Rg', 'R_g', fmtOhm)]
		},
		{
			label: 'Figures of Merit',
			rows: [col('FoM'), col('FoMqsw'), col('FoMqrr'), col('FoMcoss')]
		}
	];

	interface Props {
		part: Part;
		onclose: () => void;
	}

	let { part, onclose }: Props = $props();

	let qgFailed = $state(false);
	let partImgFailed = $state(false);

	const qgSrc = $derived(
		`/api/qg-curve?mfr=${encodeURIComponent(part.mfr)}&mpn=${encodeURIComponent(part.mpn)}`
	);

	const partImgSrc = $derived(
		`/api/part-image?mfr=${encodeURIComponent(part.mfr)}&mpn=${encodeURIComponent(part.mpn)}`
	);

	const datasheetHref = $derived(
		`/api/datasheet?mfr=${encodeURIComponent(part.mfr)}&mpn=${encodeURIComponent(part.mpn)}`
	);

	$effect(() => {
		// reset when part changes
		void part;
		qgFailed = false;
		partImgFailed = false;
	});

	function handleKey(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}

	function onBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) onclose();
	}

	function zoom(
		_node: Element,
		{ duration = 500, delay = 0 }: { duration?: number; delay?: number } = {}
	): TransitionConfig {
		return {
			duration,
			delay,
			easing: cubicOut,
			css: (t) => `transform: scale(${t});`
		};
	}
</script>

<svelte:window onkeydown={handleKey} />

<div
	class="backdrop"
	role="presentation"
	onclick={onBackdropClick}
	onkeydown={(e) => e.key === 'Escape' && onclose()}
	transition:fade={{ duration: 250, easing: cubicOut }}
>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-labelledby="part-modal-title"
		in:zoom={{ duration: 250 }}
		out:zoom={{ duration: 250 }}
	>
		<header class="modal-head">
			<div class="title-block">
				<span class="mfr-label">{part.mfr}</span>
				<h2 id="part-modal-title">{part.mpn}</h2>
			</div>
			<button type="button" class="close-btn" aria-label="close" onclick={onclose}>×</button>
		</header>

		<div class="modal-body">
			<section class="props">
				{#if !partImgFailed}
					<a
						class="part-img-link"
						href={datasheetHref}
						target="_blank"
						rel="noopener"
						title="open datasheet (PDF)"
					>
						<img
							class="part-img"
							src={partImgSrc}
							alt="package photo for {part.mpn}"
							onerror={() => (partImgFailed = true)}
						/>
					</a>
				{/if}
				<h3>Properties</h3>
				<table>
					<tbody>
						{#each GROUPS as g}
							{@const visible = g.rows
								.map((r) => ({ r, val: r.fmt(part) }))
								.filter((x) => x.val !== '')}
							{#if visible.length > 0}
								<tr class="group">
									<th colspan="2">{g.label}</th>
								</tr>
								{#each visible as { r, val } (r.key)}
									<tr>
										<th>{r.label}</th>
										<td>{val}</td>
									</tr>
								{/each}
							{/if}
						{/each}
					</tbody>
				</table>
				<a class="ds-link" href={datasheetHref} target="_blank" rel="noopener">
					→ open datasheet (PDF)
				</a>
			</section>

			<section class="chart">
				<h3>Gate-charge curve</h3>
				{#if qgFailed}
					<div class="chart-missing">
						<span class="missing-tag">N/A</span>
						<span>no gate-charge crop on file for this part</span>
					</div>
				{:else}
					<img
						src={qgSrc}
						alt="gate charge curve for {part.mpn}"
						onerror={() => (qgFailed = true)}
					/>
				{/if}
			</section>
		</div>
	</div>
</div>

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.55);
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 24px;
	}
	.modal {
		background: var(--bg-paper);
		color: var(--text);
		border: 1px solid var(--border);
		box-shadow: 6px 6px 0 var(--border-thin);
		max-width: 980px;
		width: 100%;
		max-height: calc(100vh - 48px);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		font-family: var(--serif);
	}
	.modal-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		padding: 14px 20px;
		border-bottom: 3px double var(--border);
		background: var(--bg);
	}
	.title-block {
		display: flex;
		align-items: baseline;
		gap: 12px;
		min-width: 0;
	}
	.mfr-label {
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.18em;
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.modal-head h2 {
		margin: 0;
		font-family: var(--mono);
		font-size: 18px;
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--text-strong);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.close-btn {
		width: 32px;
		height: 32px;
		padding: 0;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		font-size: 22px;
		line-height: 1;
		cursor: pointer;
		flex-shrink: 0;
	}
	.close-btn:hover {
		background: var(--text);
		color: var(--text-on-dark);
	}
	.modal-body {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
		gap: 0;
		overflow: auto;
	}
	.props,
	.chart {
		padding: 18px 20px;
		min-width: 0;
	}
	.props {
		border-right: 1px solid var(--border-thin);
	}
	.part-img-link {
		display: block;
		width: fit-content;
		margin: 0 auto 14px;
	}
	.part-img-link:hover .part-img {
		border-color: var(--text-accent);
	}
	.part-img {
		display: block;
		max-width: 100%;
		max-height: 180px;
		object-fit: contain;
		background: #fff;
		border: 1px solid var(--border-thin);
		padding: 6px;
		transition: border-color 120ms ease;
	}
	h3 {
		margin: 0 0 12px;
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.18em;
		text-transform: uppercase;
		color: var(--text-strong);
		border-bottom: 1px solid var(--border-thin);
		padding-bottom: 6px;
	}
	.props table {
		width: 100%;
		border-collapse: collapse;
		font-family: var(--mono);
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.props tbody tr {
		border-bottom: 1px solid var(--border-row);
	}
	.props tbody tr:last-child {
		border-bottom: none;
	}
	.props tr.group th {
		text-align: left;
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.18em;
		text-transform: uppercase;
		color: var(--text-strong);
		padding: 16px 0 4px;
		width: auto;
		border-bottom: 1px solid var(--border-thin);
	}
	.props tr.group:first-child th {
		padding-top: 0;
	}
	.props tr.group {
		border-bottom: none;
	}
	.props th {
		text-align: left;
		font-weight: 500;
		color: var(--text-muted);
		padding: 5px 10px 5px 0;
		white-space: nowrap;
		width: 38%;
	}
	.props td {
		text-align: right;
		padding: 5px 0;
		color: var(--text);
	}
	.ds-link {
		display: inline-block;
		margin-top: 14px;
		font-family: var(--mono);
		font-size: 12px;
		color: var(--text-accent);
		text-decoration: none;
		border-bottom: 1px solid var(--text-accent);
		padding-bottom: 1px;
	}
	.ds-link:hover {
		color: var(--text-accent-strong);
		border-bottom-color: var(--text-accent-strong);
	}
	.chart {
		display: flex;
		flex-direction: column;
	}
	.chart img {
		max-width: 100%;
		max-height: 480px;
		object-fit: contain;
		background: #fff;
		border: 1px solid var(--border-thin);
		padding: 8px;
		align-self: flex-start;
	}
	.chart-missing {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 24px 16px;
		border: 1px dashed var(--border-thin);
		font-family: var(--mono);
		font-size: 12px;
		color: var(--text-muted);
	}
	.missing-tag {
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.18em;
		padding: 2px 6px;
		border: 1px solid var(--border);
		color: var(--text);
		background: var(--bg);
	}
	@media (max-width: 768px) {
		.backdrop {
			padding: 0;
		}
		.modal {
			max-height: 100vh;
			border: none;
			box-shadow: none;
		}
		.modal-body {
			grid-template-columns: 1fr;
		}
		.props {
			border-right: none;
			border-bottom: 1px solid var(--border-thin);
		}
	}
</style>
