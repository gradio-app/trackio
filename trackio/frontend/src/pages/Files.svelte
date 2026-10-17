<script>
  import FileList from "../components/FileList.svelte";
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getProjectFiles } from "../lib/api.js";

  let { project = null } = $props();

  let files = $state([]);
  let loading = $state(false);

  async function loadFiles() {
    if (!project) {
      files = [];
      return;
    }
    loading = true;
    try {
      files = await getProjectFiles(project);
    } catch {
      files = [];
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    loadFiles();
  });
</script>

<div class="files-page">
  {#if loading}
    <LoadingTrackio />
  {:else if files.length === 0}
    <div class="empty-state">
      <h2>No project files yet</h2>
      <p>
        Files are stored at the <strong>project</strong> level (not tied to a single run). After
        <code>trackio.init()</code>, copy artifacts into the project with <code>trackio.save()</code>:
      </p>
      <pre><code>{'import trackio\n\ntrackio.init(project="my-project")\ntrackio.save("config.yaml")\ntrackio.save("checkpoints/*.pt")'}</code></pre>
      <p>Paths can be a single file or a glob. Saved files will list here for download.</p>
    </div>
  {:else}
    <h2 class="page-title">Files</h2>
    <p class="page-subtitle">Showing files saved across all runs in this project.</p>
    <FileList {files} />
  {/if}
</div>

<style>
  .files-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  .page-title {
    color: var(--body-text-color, #1f2937);
    font-size: 16px;
    font-weight: 700;
    margin: 0 0 4px;
  }
  .page-subtitle {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
    margin: 0 0 16px;
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
