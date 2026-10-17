<script>
  import { getFileUrl } from "../lib/api.js";
  import { formatSize } from "../lib/format.js";

  let { files = [], tail = false } = $props();

  let expandedFile = $state(null);
  let previewContent = $state(null);
  let previewLoading = $state(false);

  const PREVIEW_LIMIT = 50000;

  const TEXT_EXTENSIONS = new Set([
    "txt", "md", "json", "yml", "yaml", "toml", "ini", "cfg",
    "csv", "tsv", "xml", "html", "css", "js", "py", "sh",
    "log", "conf", "env", "gitignore", "dockerfile",
  ]);

  function isPreviewable(name) {
    const ext = name.split(".").pop().toLowerCase();
    return TEXT_EXTENSIONS.has(ext);
  }

  function truncate(text) {
    if (text.length <= PREVIEW_LIMIT) return text;
    return tail
      ? "(truncated) …\n\n" + text.slice(-PREVIEW_LIMIT)
      : text.slice(0, PREVIEW_LIMIT) + "\n\n… (truncated)";
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
      previewContent = truncate(await resp.text());
    } catch {
      previewContent = null;
    } finally {
      previewLoading = false;
    }
  }
</script>

<div class="file-list">
  {#each files as file}
    <div class="file-item">
      <div class="file-row">
        <button class="file-name" onclick={() => togglePreview(file)}>
          <span class="file-icon">{isPreviewable(file.name) ? "📄" : "📦"}</span>
          {file.name}
        </button>
        <div class="file-actions">
          {#if file.size != null}
            <span class="file-size">{formatSize(file.size)}</span>
          {/if}
          <a class="download-btn" href={getFileUrl(file.path)} download={file.name} title="Download">
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

<style>
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
</style>
