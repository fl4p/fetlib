<script lang="ts">
	import RangeSliderPips from 'svelte-range-slider-pips';

	interface Props {
		min: number;
		max: number;
		values: [number, number];
		step?: number;
		formatter?: (v: number) => string;
		onchange?: (values: [number, number]) => void;
	}

	let { min, max, values, step, formatter, onchange }: Props = $props();

	const range = $derived(Math.max(max - min, 1e-12));
	const resolvedStep = $derived(step ?? Math.max(range / 200, 1e-9));
</script>

<div class="rs-wrap">
	<RangeSliderPips
		{min}
		{max}
		step={resolvedStep}
		values={[values[0], values[1]]}
		range
		float
		pips={false}
		formatter={formatter ?? ((v: number) => v.toString())}
		on:change={(e) => onchange?.([e.detail.values[0], e.detail.values[1]])}
	/>
</div>

<style>
	.rs-wrap {
		padding: 0.6rem 0.5rem 0.2rem;
	}
	.rs-wrap :global(.rangeSlider) {
		--range-handle-inactive: #6b7280;
		--range-handle: #2563eb;
		--range-handle-focus: #1d4ed8;
		--range-range: #93c5fd;
		--range-float-text: #ffffff;
		--range-float: #1d4ed8;
		font-size: 12px;
		height: 8px;
	}
</style>
