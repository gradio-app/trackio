<script>
  import { getColorForIndex } from "../lib/stores.js";

  let {
    runs = [],
    value = $bindable(null),
    includeAllOption = false,
    allLabel = "All runs",
  } = $props();

  let choices = $derived(includeAllOption ? [allLabel, ...runs] : [...runs]);

  function dotColor(index) {
    if (includeAllOption && index === 0) {
      return "#9ca3af";
    }
    const idx = includeAllOption ? index - 1 : index;
    return getColorForIndex(idx);
  }
</script>

<div class="radio-group">
  {#each choices as choice, i}
    <label class="run-row">
      <input
        type="radio"
        name="trackio-compact-run"
        checked={value === choice}
        onchange={() => (value = choice)}
      />
      <span class="color-dot" style:background={dotColor(i)}></span>
      <span class="run-name" title={choice}>{choice}</span>
    </label>
  {/each}
</div>

<style>
  .radio-group {
    display: flex;
    flex-direction: column;
    max-height: 300px;
    overflow-y: auto;
    margin-top: 8px;
  }
  .run-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    cursor: pointer;
    font-size: 13px;
  }
  .run-row input[type="radio"] {
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    margin: 0;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: 50%;
    background-color: var(--checkbox-background-color, white);
    cursor: pointer;
    flex-shrink: 0;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .run-row input[type="radio"]:checked {
    border-color: var(--checkbox-border-color-selected, #f97316);
    box-shadow: inset 0 0 0 3px var(--checkbox-background-color-selected, #f97316);
  }
  .color-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .run-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--body-text-color, #1f2937);
  }
</style>
