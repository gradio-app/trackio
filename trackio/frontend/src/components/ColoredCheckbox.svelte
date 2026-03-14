<script>
  let {
    choices = [],
    selected = $bindable([]),
    colors = [],
  } = $props();

  let allSelected = $derived(
    choices.length > 0 && selected.length === choices.length,
  );

  let latestOnly = $state(false);

  function toggle(run) {
    if (selected.includes(run)) {
      selected = selected.filter((r) => r !== run);
    } else {
      selected = [...selected, run];
    }
    latestOnly = false;
  }

  function toggleAll() {
    if (allSelected) {
      selected = [];
    } else {
      selected = [...choices];
    }
    latestOnly = false;
  }

  function toggleLatestOnly() {
    latestOnly = !latestOnly;
    if (latestOnly && choices.length > 0) {
      selected = [choices[choices.length - 1]];
    } else if (!latestOnly) {
      selected = [...choices];
    }
  }
</script>

<div class="checkbox-group">
  <div class="header-row">
    <label class="header-check">
      <input
        type="checkbox"
        checked={allSelected}
        onchange={toggleAll}
      />
      <span>Runs ({choices.length})</span>
    </label>
    <label class="latest-toggle">
      <span>Latest only</span>
      <input
        type="checkbox"
        checked={latestOnly}
        onchange={toggleLatestOnly}
      />
    </label>
  </div>
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
    gap: 0;
  }
  .header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    margin-bottom: 4px;
  }
  .header-check {
    display: flex;
    align-items: center;
    gap: var(--spacing-lg, 8px);
    font-size: 13px;
    font-weight: 500;
    color: var(--body-text-color, #1f2937);
    cursor: pointer;
  }
  .header-check input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 16px;
    height: 16px;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    box-shadow: var(--checkbox-shadow);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.15s, border-color 0.15s;
  }
  .header-check input[type="checkbox"]:checked {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #2563eb);
    border-color: var(--checkbox-border-color-selected, #2563eb);
  }
  .latest-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
  }
  .latest-toggle input[type="checkbox"] {
    appearance: none;
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border: 1px solid var(--checkbox-border-color, #d1d5db);
    border-radius: var(--checkbox-border-radius, 4px);
    background-color: var(--checkbox-background-color, white);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.15s, border-color 0.15s;
  }
  .latest-toggle input[type="checkbox"]:checked {
    background-image: var(--checkbox-check);
    background-color: var(--checkbox-background-color-selected, #2563eb);
    border-color: var(--checkbox-border-color-selected, #2563eb);
  }
  .checkbox-item {
    display: flex;
    align-items: center;
    gap: var(--spacing-lg, 8px);
    padding: 4px 0;
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
    background-color: var(--checkbox-background-color-selected, #2563eb);
    border-color: var(--checkbox-border-color-selected, #2563eb);
  }
  .checkbox-item input[type="checkbox"]:hover {
    border-color: var(--checkbox-border-color-hover, #d1d5db);
  }
  .color-dot {
    width: 12px;
    height: 12px;
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
