<script>
  let {
    choices = [],
    selected = $bindable([]),
    colors = [],
    ontoggle = null,
  } = $props();

  function toggle(run) {
    if (selected.includes(run)) {
      selected = selected.filter((r) => r !== run);
    } else {
      selected = [...selected, run];
    }
    ontoggle?.();
  }
</script>

<div class="checkbox-group">
  {#each choices as run, i}
    <label class="checkbox-item">
      <input
        type="checkbox"
        checked={selected.includes(run)}
        onchange={() => toggle(run)}
      />
      <span class="color-dot" style="background: {colors[i] || '#999'}"></span>
      <span class="run-name" title={run}>{run}</span>
    </label>
  {/each}
</div>

<style>
  .checkbox-group {
    display: flex;
    flex-direction: column;
  }
  .checkbox-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    cursor: pointer;
    font-size: 13px;
  }

  .checkbox-item input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    margin: 0;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    box-shadow: var(--checkbox-shadow);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.15s, border-color 0.15s;
  }
  .checkbox-item input[type="checkbox"]:checked {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #f97316);
    border-color: var(--checkbox-border-color-selected, #f97316);
  }
  .checkbox-item input[type="checkbox"]:hover {
    border-color: var(--checkbox-border-color-hover, #d1d5db);
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
