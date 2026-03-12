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
    gap: 8px;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    cursor: pointer;
  }
  .header-check input {
    width: 15px;
    height: 15px;
    accent-color: var(--accent-color);
    cursor: pointer;
  }
  .latest-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-secondary);
    cursor: pointer;
  }
  .latest-toggle input {
    width: 14px;
    height: 14px;
    accent-color: var(--accent-color);
    cursor: pointer;
  }
  .checkbox-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    cursor: pointer;
    font-size: 13px;
  }
  .checkbox-item input {
    width: 15px;
    height: 15px;
    margin: 0;
    accent-color: var(--accent-color);
    cursor: pointer;
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
    color: var(--text-primary);
  }
</style>
