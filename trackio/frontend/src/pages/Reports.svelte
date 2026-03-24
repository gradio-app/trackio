<script>
  import { getAlerts } from "../lib/api.js";

  let { project = null, selectedRun = $bindable("All runs") } = $props();

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
    <div class="empty-state">
      <h2>No alerts yet</h2>
      <p>
        Alerts are recorded when your training script calls <code>trackio.alert()</code>. They appear here and in the
        alert panel, and can optionally POST to a webhook configured in <code>trackio.init()</code>.
      </p>
      <pre><code>{'import trackio\nfrom trackio import AlertLevel\n\ntrackio.init(project="my-project")\ntrackio.alert("Low validation loss", text="Consider saving a checkpoint.", level=AlertLevel.INFO)\ntrackio.alert("NaNs detected", level=AlertLevel.ERROR)'}</code></pre>
      <p>Use <code>AlertLevel.INFO</code>, <code>AlertLevel.WARN</code>, or <code>AlertLevel.ERROR</code>. Filter by level with the pills above.</p>
    </div>
  {:else}
    <table class="alerts-table">
      <thead>
        <tr>
          {#each tableHeaders as header}
            <th>{header}</th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each tableRows as row}
          <tr>
            {#each row as cell}
              <td>{cell}</td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
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
  .loading {
    padding: 40px;
    text-align: center;
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .empty-state {
    max-width: 640px;
    padding: 40px 24px;
    color: var(--body-text-color, #1f2937);
  }
  .empty-state h2 {
    margin: 0 0 8px;
    font-size: 20px;
    font-weight: 700;
  }
  .empty-state p {
    margin: 12px 0 8px;
    color: var(--body-text-color-subdued, #6b7280);
  }
  .empty-state pre {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 16px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: 13px;
    overflow-x: auto;
  }
  .empty-state code {
    background: var(--background-fill-secondary, #f0f0f0);
    padding: 1px 5px;
    border-radius: var(--radius-sm, 4px);
    font-size: 13px;
  }
  .empty-state pre code {
    background: none;
    padding: 0;
  }
  .alerts-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-md, 14px);
  }
  .alerts-table th {
    text-align: left;
    padding: 8px 12px;
    border-bottom: 2px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    font-weight: 600;
    font-size: var(--text-sm, 12px);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .alerts-table td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color, #1f2937);
  }
  .alerts-table tbody tr:nth-child(even) {
    background: var(--table-even-background, #f9fafb);
  }
  .alerts-table tr:hover {
    background: var(--background-fill-secondary, #f3f4f6);
  }
</style>
