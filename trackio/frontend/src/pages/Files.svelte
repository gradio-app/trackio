<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getMediaUrl, getProjectFiles } from "../lib/api.js";

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
    <h2>Files</h2>
    <ul class="file-list">
      {#each files as file}
        <li>
          <a href={getMediaUrl(file.path)} download>{file.name}</a>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .files-page {
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }
  h2 {
    color: var(--body-text-color, #1f2937);
    font-size: var(--text-xl, 22px);
    margin-bottom: 16px;
  }
  .file-list {
    list-style: none;
    padding: 0;
  }
  .file-list li {
    padding: 8px 12px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    margin-bottom: 4px;
  }
  .file-list a {
    color: var(--secondary-600, #2563eb);
    text-decoration: none;
    font-size: var(--text-md, 14px);
  }
  .file-list a:hover {
    text-decoration: underline;
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
