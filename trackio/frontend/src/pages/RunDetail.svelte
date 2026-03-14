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
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .detail-card {
    background: var(--background-fill-primary, white);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    padding: 24px;
    max-width: 800px;
  }
  .detail-card h2 {
    color: var(--body-text-color, #1f2937);
    margin: 0 0 16px;
    font-size: var(--text-xl, 22px);
  }
  .detail-card h3 {
    color: var(--body-text-color, #1f2937);
    margin: 20px 0 8px;
    font-size: var(--text-lg, 16px);
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
    font-size: var(--text-xs, 10px);
    font-weight: 600;
    color: var(--body-text-color-subdued, #9ca3af);
    text-transform: uppercase;
  }
  .detail-value {
    font-size: var(--text-md, 14px);
    color: var(--body-text-color, #1f2937);
  }
  .config-block {
    background: var(--background-fill-secondary, #f9fafb);
    padding: 12px;
    border-radius: var(--radius-lg, 8px);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    overflow-x: auto;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--body-text-color-subdued, #9ca3af);
  }
</style>
