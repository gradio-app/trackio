<script>
  import { tick } from "svelte";

  let {
    label = "Slider",
    info = "",
    value = $bindable(0),
    min = 0,
    max = 100,
    step = 1,
    showLabel = true,
  } = $props();

  let rangeInput;
  const initialValue = value;

  let percentage = $derived.by(() => {
    if (value > max) return 100;
    if (value < min) return 0;
    return ((value - min) / (max - min)) * 100;
  });

  $effect(() => {
    if (rangeInput) {
      rangeInput.style.setProperty("--range_progress", `${percentage}%`);
    }
  });

  function resetValue() {
    value = initialValue;
  }

  function clamp() {
    value = Math.min(Math.max(value, min), max);
  }
</script>

<div class="slider-wrap">
  <div class="head">
    {#if showLabel}
      <span class="label">{label}</span>
    {/if}
  </div>
  {#if info}
    <span class="info">{info}</span>
  {/if}
  <div class="slider-input-container">
    <span class="bound">{min}</span>
    <input
      type="range"
      bind:value
      bind:this={rangeInput}
      {min}
      {max}
      {step}
    />
    <span class="bound">{max}</span>
  </div>
</div>

<style>
  .slider-wrap {
    display: flex;
    flex-direction: column;
    width: 100%;
  }
  .head {
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
  }
  .label {
    flex: 1;
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .info {
    display: block;
    font-size: 12px;
    color: var(--body-text-color-subdued, #9ca3af);
    margin-bottom: 4px;
  }
  .slider-input-container {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  input[type="range"] {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    cursor: pointer;
    outline: none;
    border-radius: var(--radius-xl, 12px);
    min-width: var(--size-28, 112px);
    background: transparent;
  }
  input[type="range"]::-webkit-slider-runnable-track {
    height: 6px;
    border-radius: var(--radius-xl, 12px);
    background: linear-gradient(
      to right,
      var(--slider-color, #f97316) var(--range_progress, 50%),
      var(--neutral-200, #e5e7eb) var(--range_progress, 50%)
    );
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    height: 14px;
    width: 14px;
    background-color: white;
    border-radius: 50%;
    margin-top: -4px;
    box-shadow:
      0 0 0 1px rgba(0, 0, 0, 0.08),
      0 1px 3px rgba(0, 0, 0, 0.12);
  }
  input[type="range"]::-moz-range-track {
    height: 6px;
    background: var(--neutral-200, #e5e7eb);
    border-radius: var(--radius-xl, 12px);
  }
  input[type="range"]::-moz-range-thumb {
    appearance: none;
    height: 14px;
    width: 14px;
    background-color: white;
    border-radius: 50%;
    border: none;
    box-shadow:
      0 0 0 1px rgba(0, 0, 0, 0.08),
      0 1px 3px rgba(0, 0, 0, 0.12);
  }
  input[type="range"]::-moz-range-progress {
    height: 6px;
    background-color: var(--slider-color, #f97316);
    border-radius: var(--radius-xl, 12px);
  }
  .bound {
    font-size: 11px;
    color: var(--body-text-color-subdued, #9ca3af);
    min-width: 12px;
    text-align: center;
  }
</style>
