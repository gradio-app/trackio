<script>
  import { getRunSummary, getMetricsForRun } from "../lib/api.js";
  import { getQueryParam } from "../lib/router.js";

  let { project = null } = $props();

  let runName = $state(null);
  let summary = $state(null);
  let loading = $state(false);

  $effect(() => {
    runName = getQueryParam("selected_run");
  });

  async function loadDetail() {
    if (!project || !runName) {
      summary = null;
      return;
    }

    loading = true;
    try {
      summary = await getRunSummary(project, runName);
    } catch (e) {
      console.error("Failed to load run detail:", e);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    runName;
    loadDetail();
  });
</script>

<div class="run-detail-page">
  {#if loading}
    <div class="loading">Loading run details...</div>
  {:else if !summary}
    <div class="empty-state">Select a run to view details.</div>
  {:else}
    <div class="detail-card">
      <h2>{summary.run}</h2>
      <div class="detail-grid">
        <div class="detail-item">
          <span class="detail-label">Project</span>
          <span class="detail-value">{summary.project}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Total Logs</span>
          <span class="detail-value">{summary.num_logs}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Last Step</span>
          <span class="detail-value">{summary.last_step ?? "N/A"}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Metrics</span>
          <span class="detail-value"
            >{summary.metrics ? summary.metrics.join(", ") : "None"}</span
          >
        </div>
      </div>

      {#if summary.config}
        <h3>Configuration</h3>
        <pre class="config-block">{JSON.stringify(summary.config, null, 2)}</pre>
      {/if}
    </div>
  {/if}
</div>

<style>
  .run-detail-page {
    padding: 16px;
    overflow-y: auto;
    flex: 1;
  }
  .detail-card {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 24px;
    max-width: 800px;
  }
  .detail-card h2 {
    color: var(--text-primary);
    margin: 0 0 16px;
    font-size: 20px;
  }
  .detail-card h3 {
    color: var(--text-primary);
    margin: 20px 0 8px;
    font-size: 15px;
  }
  .detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }
  .detail-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .detail-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
  }
  .detail-value {
    font-size: 14px;
    color: var(--text-primary);
  }
  .config-block {
    background: var(--bg-secondary);
    padding: 12px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    font-size: 12px;
    color: var(--text-secondary);
    overflow-x: auto;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
  }
</style>
