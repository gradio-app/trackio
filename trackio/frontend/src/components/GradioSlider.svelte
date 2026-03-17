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
      <span class="block-title">{label}</span>
    {/if}
    <div class="tab-like-container">
      <input
        type="number"
        bind:value
        {min}
        {max}
        {step}
        onblur={clamp}
      />
      <button
        class="reset-button"
        onclick={resetValue}
        aria-label="Reset to default value"
      >
        ↺
      </button>
    </div>
  </div>
  {#if info}
    <span class="block-info">{info}</span>
  {/if}
  <div class="slider-input-container">
    <span class="min-value">{min}</span>
    <input
      type="range"
      bind:value
      bind:this={rangeInput}
      {min}
      {max}
      {step}
    />
    <span class="max-value">{max}</span>
  </div>
</div>

<style>
  .slider-wrap {
    display: flex;
    flex-direction: column;
    width: 100%;
  }
  .head {
    margin-bottom: var(--size-2, 8px);
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    width: 100%;
  }
  .head > .block-title {
    flex: 1;
  }
  .block-title {
    display: block;
    font-size: var(--block-title-text-size, 14px);
    font-weight: var(--block-title-text-weight, 400);
    color: var(--block-title-text-color, #6b7280);
    margin-bottom: 2px;
  }
  .block-info {
    display: block;
    font-size: var(--block-info-text-size, 12px);
    color: var(--block-info-text-color, #9ca3af);
    margin-bottom: var(--spacing-md, 6px);
  }
  .slider-input-container {
    display: flex;
    align-items: center;
    gap: var(--size-2, 8px);
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
    height: var(--size-2, 8px);
    border-radius: var(--radius-xl, 12px);
    background: linear-gradient(
      to right,
      var(--slider-color, #2563eb) var(--range_progress, 50%),
      var(--neutral-200, #e5e7eb) var(--range_progress, 50%)
    );
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    height: var(--size-4, 16px);
    width: var(--size-4, 16px);
    background-color: white;
    border-radius: 50%;
    margin-top: -4px;
    box-shadow:
      0 0 0 1px rgba(247, 246, 246, 0.739),
      1px 1px 4px rgba(0, 0, 0, 0.1);
  }
  input[type="range"]::-moz-range-track {
    height: var(--size-2, 8px);
    background: var(--neutral-200, #e5e7eb);
    border-radius: var(--radius-xl, 12px);
  }
  input[type="range"]::-moz-range-thumb {
    appearance: none;
    height: var(--size-4, 16px);
    width: var(--size-4, 16px);
    background-color: white;
    border-radius: 50%;
    border: none;
    box-shadow:
      0 0 0 1px rgba(247, 246, 246, 0.739),
      1px 1px 4px rgba(0, 0, 0, 0.1);
  }
  input[type="range"]::-moz-range-progress {
    height: var(--size-2, 8px);
    background-color: var(--slider-color, #2563eb);
    border-radius: var(--radius-xl, 12px);
  }
  .tab-like-container {
    display: flex;
    align-items: stretch;
    border: 1px solid var(--input-border-color, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    overflow: hidden;
    height: var(--size-6, 24px);
  }
  input[type="number"] {
    display: block;
    outline: none;
    border: none;
    border-radius: 0;
    background: var(--input-background-fill, white);
    padding: var(--size-1, 4px) var(--size-2, 8px);
    height: 100%;
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-sm, 12px);
    line-height: var(--line-sm, 1.4);
    text-align: center;
    min-width: var(--size-14, 56px);
    font-family: inherit;
  }
  input[type="number"]:focus {
    box-shadow: inset 0 0 0 1px var(--color-accent, #f97316);
    border-radius: 3px 0 0 3px;
  }
  input[type="number"]::-webkit-inner-spin-button,
  input[type="number"]::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  input[type="number"] {
    -moz-appearance: textfield;
  }
  .reset-button {
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    border-left: 1px solid var(--input-border-color, #e5e7eb);
    cursor: pointer;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    padding: 0 var(--size-2, 8px);
    min-width: var(--size-6, 24px);
    transition: background-color 0.15s ease-in-out;
  }
  .reset-button:hover {
    background-color: var(--background-fill-secondary, #f9fafb);
  }
  .min-value,
  .max-value {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .min-value {
    margin-right: var(--size-0-5, 2px);
  }
  .max-value {
    margin-left: var(--size-0-5, 2px);
    margin-right: var(--size-0-5, 2px);
  }
</style>
