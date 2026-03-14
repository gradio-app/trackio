<script>
  import Dropdown from "../components/Dropdown.svelte";
  import GradioTable from "../components/GradioTable.svelte";
  import { getAlerts } from "../lib/api.js";

  let { project = null, runs = [] } = $props();

  let selectedRun = $state(null);
  let alerts = $state([]);
  let filterLevel = $state(null);
  let loading = $state(false);

  let runChoices = $derived(["All runs", ...runs]);

  const BADGES = { info: "🔵", warn: "🟡", error: "🔴" };

  async function loadAlerts() {
    if (!project) {
      alerts = [];
      return;
    }

    loading = true;
    try {
      const actualRun = selectedRun === "All runs" ? null : selectedRun;
      const data = await getAlerts(project, actualRun, filterLevel, null);
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

  let tableHeaders = ["Level", "Run", "Title", "Text", "Step", "Time"];
  let tableRows = $derived(
    alerts.map(a => [
      `${BADGES[a.level] || ""} ${a.level}`,
      a.run || "",
      a.title,
      a.text || "",
      a.step ?? "",
      formatTimestamp(a.timestamp),
    ])
  );
</script>

<div class="reports-page">
  <div class="controls">
    <div class="control">
      <Dropdown
        label="Run"
        choices={runChoices}
        bind:value={selectedRun}
        filterable={true}
      />
    </div>
    <div class="control">
      <span class="block-title">Level</span>
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
    <GradioTable
      headers={tableHeaders}
      rows={tableRows}
    />
  {/if}
</div>

<style>
  .reports-page {
    padding: 20px 24px;
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
  .block-title {
    display: block;
    font-size: var(--block-title-text-size, 14px);
    font-weight: var(--block-title-text-weight, 400);
    color: var(--block-title-text-color, #6b7280);
    margin-bottom: var(--spacing-lg, 8px);
  }
  .filter-pills {
    display: flex;
    gap: 4px;
  }
  .pill {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-xxl, 22px);
    padding: 4px 12px;
    font-size: var(--text-sm, 12px);
    background: var(--background-fill-secondary, #f9fafb);
    color: var(--body-text-color-subdued, #6b7280);
    cursor: pointer;
    transition: background-color 0.15s, color 0.15s;
  }
  .pill:hover {
    background: var(--neutral-100, #f3f4f6);
  }
  .pill.active {
    background: var(--color-accent, #f97316);
    color: white;
    border-color: var(--color-accent, #f97316);
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--body-text-color-subdued, #9ca3af);
  }
</style>
