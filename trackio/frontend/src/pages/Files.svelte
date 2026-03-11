<script>
  import { getMediaUrl } from "../lib/api.js";

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
      const resp = await fetch(
        `/gradio_api/call/get_logs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: [project, "__files__"] }),
        },
      );
      files = [];
    } catch (e) {
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
  <h2>Files</h2>
  {#if loading}
    <div class="loading">Loading files...</div>
  {:else if files.length === 0}
    <div class="empty-state">
      <p>No files found for this project.</p>
      <p>Upload files using:</p>
      <pre><code>trackio.save("my_file.py")</code></pre>
    </div>
  {:else}
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
    padding: 16px;
    overflow-y: auto;
    flex: 1;
  }
  h2 {
    color: var(--text-primary);
    font-size: 18px;
    margin-bottom: 16px;
  }
  .file-list {
    list-style: none;
    padding: 0;
  }
  .file-list li {
    padding: 8px 12px;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-sm);
    margin-bottom: 4px;
  }
  .file-list a {
    color: var(--accent-color);
    text-decoration: none;
  }
  .file-list a:hover {
    text-decoration: underline;
  }
  .loading,
  .empty-state {
    padding: 40px;
    text-align: center;
    color: var(--text-secondary);
  }
  .empty-state pre {
    display: inline-block;
    text-align: left;
    background: var(--bg-secondary);
    padding: 12px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    font-size: 13px;
  }
</style>
