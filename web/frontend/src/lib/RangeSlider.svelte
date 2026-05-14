<script lang="ts">
	import { onDestroy } from 'svelte';
	import RangeSliderPips from 'svelte-range-slider-pips';

	interface Props {
		min: number;
		max: number;
		values: [number, number];
		step?: number;
		log?: boolean;
		formatter?: (v: number) => string;
		onchange?: (values: [number, number]) => void;
		onpending?: (pending: boolean) => void;
		debounceMs?: number;
	}

	let {
		min,
		max,
		values,
		step,
		log = false,
		formatter,
		onchange,
		onpending,
		debounceMs = 200
	}: Props = $props();

	const useLog = $derived(log && min > 0 && max > 0);
	const sliderMin = $derived(useLog ? Math.log10(min) : min);
	const sliderMax = $derived(useLog ? Math.log10(max) : max);
	const sliderValues = $derived<[number, number]>(
		useLog
			? [Math.log10(Math.max(values[0], min)), Math.log10(Math.max(values[1], min))]
			: [values[0], values[1]]
	);

	function fromSliderSpace(v: number): number {
		return useLog ? Math.pow(10, v) : v;
	}

	const range = $derived(Math.max(sliderMax - sliderMin, 1e-12));
	const resolvedStep = $derived(step ?? Math.max(range / 200, useLog ? 1e-4 : 1e-9));

	const displayFormatter = $derived((v: number) => {
		const real = fromSliderSpace(v);
		return formatter ? formatter(real) : real.toString();
	});

	let pending: [number, number] | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let isPending = false;

	function schedule(v: [number, number]) {
		pending = v;
		if (!isPending) {
			isPending = true;
			onpending?.(true);
		}
		if (timer) clearTimeout(timer);
		timer = setTimeout(flush, debounceMs);
	}

	function flush() {
		if (timer) {
			clearTimeout(timer);
			timer = null;
		}
		if (pending !== null) {
			onchange?.(pending);
			pending = null;
		}
		if (isPending) {
			isPending = false;
			onpending?.(false);
		}
	}

	onDestroy(() => {
		if (timer) clearTimeout(timer);
	});
</script>

<div class="rs-wrap">
	<RangeSliderPips
		min={sliderMin}
		max={sliderMax}
		step={resolvedStep}
		precision={15}
		values={sliderValues}
		range
		float
		pips={false}
		formatter={displayFormatter}
		on:change={(e) =>
			schedule([fromSliderSpace(e.detail.values[0]), fromSliderSpace(e.detail.values[1])])}
		on:stop={() => flush()}
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
