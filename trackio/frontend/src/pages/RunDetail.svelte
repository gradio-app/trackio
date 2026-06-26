<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getRunSummary, getRunArtifacts } from "../lib/api.js";
  import { getQueryParam, navigateTo, setQueryParam } from "../lib/router.js";

  let { project = null } = $props();

  let runName = $state(null);
  let runId = $state(null);
  let summary = $state(null);
  let loading = $state(false);
  let runArtifacts = $state({ input: [], output: [] });

  function formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function openArtifact(name) {
    setQueryParam("selected_artifact", name);
    navigateTo("artifacts");
  }

  $effect(() => {
    runId = getQueryParam("selected_run_id");
    runName = getQueryParam("selected_run");
  });

  async function loadDetail() {
    if (!project || (!runName && !runId)) {
      summary = null;
      runArtifacts = { input: [], output: [] };
      return;
    }

    loading = true;
    try {
      const loadedSummary = await getRunSummary(
        project,
        runId ? { id: runId, name: runName } : runName,
      );
      summary = loadedSummary;
      if (loadedSummary?.run) {
        runName = loadedSummary.run;
      }
    } catch (e) {
      console.error("Failed to load run detail:", e);
    } finally {
      loading = false;
    }
    try {
      runArtifacts = await getRunArtifacts(
        project,
        runId ? { id: runId, name: runName } : runName,
      );
    } catch {
      runArtifacts = { input: [], output: [] };
    }
  }

  $effect(() => {
    project;
    runName;
    runId;
    loadDetail();
  });
</script>

<div class="run-detail-page">
  {#if loading}
    <LoadingTrackio />
  {:else if !summary}
    <div class="empty-state">
      <h2>Open a run</h2>
      <p>
        Choose a run from the <strong>Runs</strong> page or follow a run name from the sidebar. This view shows the
        project name, log count, last step, metric keys, and any logged config.
      </p>
      <pre><code>{'import trackio\ntrackio.init(project="my-project", config={"lr": 1e-3})\ntrackio.log({"loss": 0.5})\ntrackio.finish()'}</code></pre>
      <p>Config passed to <code>trackio.init()</code> appears under Configuration when present.</p>
    </div>
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

      {#if runArtifacts.output.length > 0}
        <h3>Output artifacts</h3>
        <div class="artifact-links">
          {#each runArtifacts.output as art}
            <button class="artifact-link" onclick={() => openArtifact(art.name)}>
              <span class="art-name"
                >{art.name}<span class="art-ver">:v{art.version}</span></span
              >
              <span class="art-type">{art.type}</span>
              <span class="art-size">{formatSize(art.size_bytes)}</span>
              <span class="art-arrow">→</span>
            </button>
          {/each}
        </div>
      {/if}

      {#if runArtifacts.input.length > 0}
        <h3>Input artifacts</h3>
        <div class="artifact-links">
          {#each runArtifacts.input as art}
            <button class="artifact-link" onclick={() => openArtifact(art.name)}>
              <span class="art-name"
                >{art.name}<span class="art-ver">:v{art.version}</span></span
              >
              <span class="art-type">{art.type}</span>
              <span class="art-size">{formatSize(art.size_bytes)}</span>
              <span class="art-arrow">→</span>
            </button>
          {/each}
        </div>
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
  .artifact-links {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .artifact-link {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    text-align: left;
    background: none;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 8px 12px;
    cursor: pointer;
  }
  .artifact-link:hover {
    border-color: var(--color-accent, #f97316);
    background: var(--background-fill-secondary, #f9fafb);
  }
  .art-name {
    font-weight: 600;
    color: var(--color-accent, #f97316);
    font-size: var(--text-md, 14px);
  }
  .art-ver {
    font-weight: 400;
    color: var(--body-text-color-subdued, #6b7280);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .art-type {
    font-size: var(--text-xs, 11px);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--body-text-color-subdued, #6b7280);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: 9px;
    padding: 1px 8px;
  }
  .art-size {
    margin-left: auto;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .art-arrow {
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
</style>
