<script>
  import { getAlerts } from "../lib/api.js";

  let { project = null, runs = [] } = $props();

  let selectedRun = $state(null);
  let alerts = $state([]);
  let filterLevel = $state(null);
  let loading = $state(false);

  const BADGES = { info: "🔵", warn: "🟡", error: "🔴" };

  async function loadAlerts() {
    if (!project) {
      alerts = [];
      return;
    }

    loading = true;
    try {
      const data = await getAlerts(project, selectedRun, filterLevel, null);
      alerts = data || [];
    } catch (e) {
      console.error("Failed to load alerts:", e);
      alerts = [];
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    selectedRun;
    filterLevel;
    loadAlerts();
  });

  function formatTimestamp(ts) {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      return d.toLocaleString();
    } catch {
      return ts;
    }
  }
</script>

<div class="reports-page">
  <div class="controls">
    <div class="control">
      <label class="label">Run</label>
      <select class="select" bind:value={selectedRun}>
        <option value={null}>All runs</option>
        {#each runs as run}
          <option value={run}>{run}</option>
        {/each}
      </select>
    </div>
    <div class="control">
      <label class="label">Level</label>
      <div class="filter-pills">
        <button
          class="pill"
          class:active={filterLevel === null}
          onclick={() => (filterLevel = null)}>All</button
        >
        <button
          class="pill"
          class:active={filterLevel === "info"}
          onclick={() => (filterLevel = "info")}>Info</button
        >
        <button
          class="pill"
          class:active={filterLevel === "warn"}
          onclick={() => (filterLevel = "warn")}>Warn</button
        >
        <button
          class="pill"
          class:active={filterLevel === "error"}
          onclick={() => (filterLevel = "error")}>Error</button
        >
      </div>
    </div>
  </div>

  {#if loading}
    <div class="loading">Loading alerts...</div>
  {:else if alerts.length === 0}
    <div class="empty-state">No alerts found.</div>
  {:else}
    <table class="alerts-table">
      <thead>
        <tr>
          <th>Level</th>
          <th>Run</th>
          <th>Title</th>
          <th>Text</th>
          <th>Step</th>
          <th>Time</th>
        </tr>
      </thead>
      <tbody>
        {#each alerts as alert}
          <tr>
            <td>{BADGES[alert.level] || ""} {alert.level}</td>
            <td>{alert.run || ""}</td>
            <td>{alert.title}</td>
            <td>{alert.text || ""}</td>
            <td>{alert.step ?? ""}</td>
            <td>{formatTimestamp(alert.timestamp)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .reports-page {
    padding: 16px;
    overflow-y: auto;
    flex: 1;
  }
  .controls {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    align-items: flex-end;
  }
  .control {
    min-width: 200px;
  }
  .label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    margin-bottom: 4px;
  }
  .select {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-sm);
    background: var(--input-bg);
    color: var(--text-primary);
    font-size: 13px;
  }
  .filter-pills {
    display: flex;
    gap: 4px;
  }
  .pill {
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 12px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    cursor: pointer;
  }
  .pill.active {
    background: var(--accent-color);
    color: white;
    border-color: var(--accent-color);
  }
  .alerts-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .alerts-table th,
  .alerts-table td {
    padding: 8px 12px;
    border: 1px solid var(--border-color);
    text-align: left;
  }
  .alerts-table th {
    background: var(--bg-secondary);
    font-weight: 600;
    color: var(--text-primary);
  }
  .alerts-table td {
    color: var(--text-secondary);
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
  }
</style>
