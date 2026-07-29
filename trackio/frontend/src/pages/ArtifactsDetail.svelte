<script>
  import ArtifactVersionDetail from "../components/ArtifactVersionDetail.svelte";

  let { project = null, selection = null, empty = false } = $props();
</script>

<div class="detail-pane">
  {#if selection}
    {#key `${selection.name}@v${selection.version}`}
      <ArtifactVersionDetail
        variant="panel"
        {project}
        name={selection.name}
        version={selection.version}
      />
    {/key}
  {:else if empty}
    <div class="empty-state">
      <h2>No artifacts in this project</h2>
      <p>
        Artifacts are versioned, content-addressed files (models, datasets, …)
        logged from a run. After <code>trackio.init()</code>, log one with
        <code>trackio.log_artifact()</code>:
      </p>
      <pre><code
          >{'import trackio\n\ntrackio.init(project="my-project")\ntrackio.log_artifact("model.pt", name="my-model", type="model")'}</code
        ></pre>
      <p>
        You can also build a multi-file artifact with
        <code>add_file()</code>/<code>add_dir()</code>. Logged artifacts list
        here, grouped by type, with their versions and files.
      </p>
    </div>
  {:else}
    <div class="detail-empty">
      Select an artifact version to view its details.
    </div>
  {/if}
</div>

<style>
  .detail-pane {
    flex: 1;
    min-width: 0;
    overflow-y: auto;
    padding: 20px 28px;
  }
  .detail-empty {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 13px);
    padding: 12px 0;
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
