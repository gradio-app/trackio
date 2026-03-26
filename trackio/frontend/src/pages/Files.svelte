<script>
  import LoadingTrackio from "../components/LoadingTrackio.svelte";
  import { getFileUrl, getProjectFiles } from "../lib/api.js";

  let { project = null } = $props();

  let files = $state([]);
  let loading = $state(false);
  let expandedFile = $state(null);
  let previewContent = $state(null);
  let previewLoading = $state(false);

  const TEXT_EXTENSIONS = new Set([
    "txt", "md", "json", "yml", "yaml", "toml", "ini", "cfg",
    "csv", "tsv", "xml", "html", "css", "js", "py", "sh",
    "log", "conf", "env", "gitignore", "dockerfile",
  ]);

  function isPreviewable(name) {
    const ext = name.split(".").pop().toLowerCase();
    return TEXT_EXTENSIONS.has(ext);
  }

  function formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function togglePreview(file) {
    if (expandedFile === file.name) {
      expandedFile = null;
      previewContent = null;
      return;
    }
    expandedFile = file.name;
    if (!isPreviewable(file.name)) {
      previewContent = null;
      return;
    }
    previewLoading = true;
    try {
      const url = getFileUrl(file.path);
      const resp = await fetch(url);
      if (!resp.ok) throw new Error("fetch failed");
      const text = await resp.text();
      previewContent = text.length > 50000 ? text.slice(0, 50000) + "\n\n… (truncated)" : text;
    } catch {
      previewContent = null;
    } finally {
      previewLoading = false;
    }
  }

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
    <div class="file-list">
      {#each files as file}
        <div class="file-item" class:expanded={expandedFile === file.name}>
          <div class="file-row">
            <button class="file-name" onclick={() => togglePreview(file)}>
              <span class="file-icon">{isPreviewable(file.name) ? "📄" : "📦"}</span>
              {file.name}
            </button>
            <div class="file-actions">
              {#if file.size != null}
                <span class="file-size">{formatSize(file.size)}</span>
              {/if}
              <a class="download-btn" href={getFileUrl(file.path)} download title="Download">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M8 1v9m0 0L5 7m3 3l3-3M2 12v1a2 2 0 002 2h8a2 2 0 002-2v-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </a>
            </div>
          </div>
          {#if expandedFile === file.name}
            <div class="file-preview">
              {#if previewLoading}
                <div class="preview-loading">Loading preview...</div>
              {:else if previewContent != null}
                <pre class="preview-code">{previewContent}</pre>
              {:else}
                <div class="preview-unavailable">
                  Preview not available. <a href={getFileUrl(file.path)} download>Download the file</a> instead.
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
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
  .file-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .file-item {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-lg, 8px);
    background: var(--background-fill-primary, white);
    overflow: hidden;
  }
  .file-item.expanded {
    border-color: var(--color-accent, #f97316);
  }
  .file-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    gap: 12px;
  }
  .file-name {
    display: flex;
    align-items: center;
    gap: 8px;
    background: none;
    border: none;
    padding: 0;
    font-size: var(--text-md, 14px);
    color: var(--body-text-color, #1f2937);
    cursor: pointer;
    text-align: left;
  }
  .file-name:hover {
    color: var(--color-accent, #f97316);
  }
  .file-icon {
    font-size: 14px;
    flex-shrink: 0;
  }
  .file-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }
  .file-size {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    white-space: nowrap;
  }
  .download-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-md, 6px);
    color: var(--body-text-color-subdued, #6b7280);
    transition: background-color 0.15s, color 0.15s;
  }
  .download-btn:hover {
    background: var(--background-fill-secondary, #f3f4f6);
    color: var(--body-text-color, #1f2937);
  }
  .file-preview {
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    padding: 12px 14px;
    background: var(--background-fill-secondary, #f9fafb);
  }
  .preview-code {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    max-height: 400px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-all;
    color: var(--body-text-color, #1f2937);
  }
  .preview-loading {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
    padding: 8px 0;
  }
  .preview-unavailable {
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 12px);
    padding: 8px 0;
  }
  .preview-unavailable a {
    color: var(--color-accent, #f97316);
    text-decoration: none;
  }
  .preview-unavailable a:hover {
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
