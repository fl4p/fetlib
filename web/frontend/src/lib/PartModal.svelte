<script lang="ts">
	import type { Part } from './types';
	import { COLUMNS } from './columns';

	interface Props {
		part: Part;
		onclose: () => void;
	}

	let { part, onclose }: Props = $props();

	let qgFailed = $state(false);

	const qgSrc = $derived(
		`/api/qg-curve?mfr=${encodeURIComponent(part.mfr)}&mpn=${encodeURIComponent(part.mpn)}`
	);

	const datasheetHref = $derived(
		`/api/datasheet?mfr=${encodeURIComponent(part.mfr)}&mpn=${encodeURIComponent(part.mpn)}`
	);

	$effect(() => {
		// reset when part changes
		void part;
		qgFailed = false;
	});

	function handleKey(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}

	function onBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) onclose();
	}
</script>

<svelte:window onkeydown={handleKey} />

<div
	class="backdrop"
	role="presentation"
	onclick={onBackdropClick}
	onkeydown={(e) => e.key === 'Escape' && onclose()}
>
	<div class="modal" role="dialog" aria-modal="true" aria-labelledby="part-modal-title">
		<header class="modal-head">
			<div class="title-block">
				<span class="mfr-label">{part.mfr}</span>
				<h2 id="part-modal-title">{part.mpn}</h2>
			</div>
			<button type="button" class="close-btn" aria-label="close" onclick={onclose}>×</button>
		</header>

		<div class="modal-body">
			<section class="props">
				<h3>Properties</h3>
				<table>
					<tbody>
						{#each COLUMNS as col}
							{@const val = col.fmt(part)}
							<tr>
								<th>{col.label}</th>
								<td>{val || '—'}</td>
							</tr>
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
