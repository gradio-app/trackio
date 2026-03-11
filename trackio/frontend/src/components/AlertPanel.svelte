<script>
  let { alerts = [] } = $props();

  const BADGES = { info: "🔵", warn: "🟡", error: "🔴" };
  let expanded = $state({});
  let filterLevel = $state(null);

  let filtered = $derived(
    filterLevel ? alerts.filter((a) => a.level === filterLevel) : alerts,
  );

  function toggleExpand(i) {
    expanded = { ...expanded, [i]: !expanded[i] };
  }
</script>

{#if alerts.length > 0}
  <div class="alert-panel">
    <div class="alert-header">
      <span class="alert-title">Alerts ({alerts.length})</span>
      <div class="filter-pills">
        <button
          class="pill"
          class:active={filterLevel === null}
          onclick={() => (filterLevel = null)}>All</button
        >
        <button
          class="pill"
          class:active={filterLevel === "info"}
          onclick={() => (filterLevel = "info")}>🔵 Info</button
        >
        <button
          class="pill"
          class:active={filterLevel === "warn"}
          onclick={() => (filterLevel = "warn")}>🟡 Warn</button
        >
        <button
          class="pill"
          class:active={filterLevel === "error"}
          onclick={() => (filterLevel = "error")}>🔴 Error</button
        >
      </div>
    </div>
    <div class="alert-list">
      {#each filtered as alert, i}
        <div class="alert-item" class:expanded={expanded[i]}>
          <button class="alert-row" onclick={() => toggleExpand(i)}>
            <span>{BADGES[alert.level] || ""}</span>
            <span class="alert-text">{alert.title}</span>
            <span class="alert-meta">{alert.meta || ""}</span>
          </button>
          {#if expanded[i] && alert.text}
            <div class="alert-detail">{alert.text}</div>
          {/if}
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .alert-panel {
    position: fixed;
    bottom: 16px;
    right: 16px;
    width: 380px;
    max-height: 400px;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
    z-index: 1000;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .alert-header {
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .alert-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .filter-pills {
    display: flex;
    gap: 4px;
  }
  .pill {
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 11px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    cursor: pointer;
  }
  .pill.active {
    background: var(--accent-color);
    color: white;
    border-color: var(--accent-color);
  }
  .alert-list {
    overflow-y: auto;
    flex: 1;
  }
  .alert-item {
    border-bottom: 1px solid var(--border-light);
  }
  .alert-row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 12px;
    border: none;
    background: none;
    text-align: left;
    cursor: pointer;
    font-size: 12px;
  }
  .alert-row:hover {
    background: var(--bg-secondary);
  }
  .alert-text {
    flex: 1;
    color: var(--text-primary);
  }
  .alert-meta {
    font-size: 10px;
    color: var(--text-muted);
    white-space: nowrap;
  }
  .alert-detail {
    padding: 4px 12px 8px 32px;
    font-size: 12px;
    color: var(--text-secondary);
  }
</style>
