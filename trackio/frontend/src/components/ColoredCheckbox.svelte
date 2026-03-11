<script>
  let {
    choices = [],
    selected = $bindable([]),
    colors = [],
  } = $props();

  let allSelected = $derived(
    choices.length > 0 && selected.length === choices.length,
  );

  function toggle(run) {
    if (selected.includes(run)) {
      selected = selected.filter((r) => r !== run);
    } else {
      selected = [...selected, run];
    }
  }

  function toggleAll() {
    if (allSelected) {
      selected = [];
    } else {
      selected = [...choices];
    }
  }

  function selectLatestOnly() {
    if (choices.length > 0) {
      selected = [choices[choices.length - 1]];
    }
  }
</script>

<div class="checkbox-group">
  <div class="actions">
    <button class="action-btn" onclick={toggleAll}>
      {allSelected ? "Deselect all" : "Select all"}
    </button>
    <button class="action-btn" onclick={selectLatestOnly}>Latest only</button>
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
    gap: 2px;
  }
  .actions {
    display: flex;
    gap: 8px;
    margin-bottom: 4px;
  }
  .action-btn {
    border: none;
    background: none;
    color: var(--accent-color);
    font-size: 11px;
    cursor: pointer;
    padding: 2px 0;
  }
  .action-btn:hover {
    text-decoration: underline;
  }
  .checkbox-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 0;
    cursor: pointer;
    font-size: 12px;
  }
  .checkbox-item input {
    margin: 0;
    accent-color: var(--accent-color);
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
    color: var(--text-primary);
  }
</style>
