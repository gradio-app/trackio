<script>
  import {
    getArtifactManifest,
    getArtifactConsumers,
    getArtifactBlobUrl,
  } from "../lib/api.js";
  import { navigateTo, setQueryParam } from "../lib/router.js";

  let { project = null, name = null, version = null } = $props();

  let record = $state(null);
  let consumers = $state([]);
  let loading = $state(false);
  let error = $state(false);

  function formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function openRun(runName, runId) {
    setQueryParam("selected_run_id", runId);
    setQueryParam("selected_run", runName);
    navigateTo("run-detail");
  }

  async function load() {
    record = null;
    consumers = [];
    error = false;
    if (!project || !name || version == null) return;
    loading = true;
    try {
      const m = await getArtifactManifest(project, name, `v${version}`);
      record = m;
      if (m?.version_id != null) {
        consumers = (await getArtifactConsumers(project, m.version_id)) || [];
      }
    } catch {
      error = true;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    project;
    name;
    version;
    load();
  });
</script>

<div class="version-detail">
  {#if loading}
    <div class="status">Loading…</div>
  {:else if error || !record}
    <div class="status">Failed to load this version.</div>
  {:else}
    <div class="detail-grid">
      {#if record.producer_run_name}
        <span class="detail-key">Produced by</span>
        <span class="detail-val">
          <button
            class="run-link"
            onclick={() =>
              openRun(record.producer_run_name, record.producer_run_id)}
            >{record.producer_run_name}</button
          >
        </span>
      {/if}
      {#if consumers.length}
        <span class="detail-key">Used by</span>
        <span class="detail-val">
          {#each consumers as c, ci}<button
              class="run-link"
              onclick={() => openRun(c.run_name, c.run_id)}
              >{c.run_name ?? c.run_id}</button
            >{ci < consumers.length - 1 ? ", " : ""}{/each}
        </span>
      {/if}
      <span class="detail-key">Digest</span>
      <span class="detail-val mono">{record.manifest_digest?.slice(0, 16)}…</span>
      {#if record.metadata && Object.keys(record.metadata).length}
        {#each Object.entries(record.metadata) as [k, v]}
          <span class="detail-key">{k}</span>
          <span class="detail-val"
            >{typeof v === "object" ? JSON.stringify(v) : String(v)}</span
          >
        {/each}
      {/if}
    </div>

    <div class="file-table">
      {#each record.manifest || [] as file}
        <div class="file-entry">
          <span class="file-path">{file.path}</span>
          <span class="spacer"></span>
          <span class="file-size">{formatSize(file.size)}</span>
          <a
            class="download-btn"
            href={getArtifactBlobUrl(project, file.digest)}
            download={file.path}
            title="Download"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M8 1v9m0 0L5 7m3 3l3-3M2 12v1a2 2 0 002 2h8a2 2 0 002-2v-1"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </a>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .version-detail {
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    padding: 10px 14px 12px;
    background: var(--background-fill-secondary, #f9fafb);
  }
  .detail-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 2px 16px;
    margin-bottom: 10px;
  }
  .detail-key {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .detail-val {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    word-break: break-word;
  }
  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .run-link {
    background: none;
    border: none;
    padding: 0;
    font-size: var(--text-sm, 12px);
    color: var(--color-accent, #f97316);
    cursor: pointer;
    text-align: left;
  }
  .run-link:hover {
    text-decoration: underline;
  }
  .file-table {
    display: flex;
    flex-direction: column;
  }
  .file-entry {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
  }
  .file-entry:first-child {
    border-top: none;
  }
  .spacer {
    flex: 1 1 auto;
  }
  .file-path {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    word-break: break-all;
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
    flex-shrink: 0;
    border-radius: var(--radius-md, 6px);
    color: var(--body-text-color-subdued, #6b7280);
    transition:
      background-color 0.15s,
      color 0.15s;
  }
  .download-btn:hover {
    background: var(--background-fill-primary, #fff);
    color: var(--color-accent, #f97316);
  }
  .status {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    padding: 4px 0;
  }
</style>
