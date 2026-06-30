<script>
  import Accordion from "./Accordion.svelte";
  import {
    getArtifactManifest,
    getArtifactConsumers,
    getArtifactBlobUrl,
  } from "../lib/api.js";
  import { navigateTo, setQueryParam } from "../lib/router.js";

  let { project = null, name = null, version = null, variant = "inline" } =
    $props();

  let record = $state(null);
  let consumers = $state([]);
  let loading = $state(false);
  let error = $state(false);
  let copied = $state("");
  let copyTimer = null;

  function formatSize(bytes) {
    if (bytes == null) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function formatDate(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function isPlainObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  function isScalarArray(v) {
    return (
      Array.isArray(v) && v.every((x) => x === null || typeof x !== "object")
    );
  }

  function isBranch(v) {
    return isPlainObject(v) || (Array.isArray(v) && !isScalarArray(v));
  }

  function formatLeaf(v) {
    if (isScalarArray(v)) return JSON.stringify(v);
    return v === null ? "null" : String(v);
  }

  function openRun(runName, runId) {
    setQueryParam("selected_run_id", runId);
    setQueryParam("selected_run", runName);
    navigateTo("run-detail");
  }

  function copy(text, which) {
    if (!text) return;
    navigator.clipboard?.writeText(text);
    copied = which;
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      if (copied === which) copied = "";
    }, 1500);
  }

  let usageSnippet = $derived(
    record ? `trackio.use_artifact("${record.name}:v${record.version}")` : "",
  );

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

{#snippet fileTable()}
  <div class="file-table">
    {#each record.manifest || [] as file}
      <a
        class="file-entry"
        href={getArtifactBlobUrl(project, file.digest)}
        download={file.path}
        title="Download {file.path}"
      >
        <span class="file-path">{file.path}</span>
        <span class="spacer"></span>
        <span class="file-digest mono" title={file.digest}
          >{file.digest?.slice(0, 12)}…</span
        >
        <span class="file-size">{formatSize(file.size)}</span>
        <span class="download-icon">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 1v9m0 0L5 7m3 3l3-3M2 12v1a2 2 0 002 2h8a2 2 0 002-2v-1"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </span>
      </a>
    {/each}
  </div>
{/snippet}

{#snippet metaRows(entries, depth)}
  {#each entries as [k, v]}
    {#if isBranch(v)}
      <span class="detail-key meta-group" style="padding-left: {depth * 14}px"
        >{k}</span
      >
      <span class="detail-val"></span>
      {@render metaRows(Object.entries(v), depth + 1)}
    {:else}
      <span class="detail-key" style="padding-left: {depth * 14}px">{k}</span>
      <span class="detail-val">{formatLeaf(v)}</span>
    {/if}
  {/each}
{/snippet}

{#if variant === "panel"}
  <div class="panel">
    {#if loading}
      <div class="status">Loading…</div>
    {:else if error || !record}
      <div class="status">Failed to load this version.</div>
    {:else}
      <header class="panel-header">
        <div class="title-row">
          <h2 class="art-name">{record.name}</h2>
          <span class="ver-badge">v{record.version}</span>
          {#each record.aliases as alias}
            <span class="alias-pill" class:latest={alias === "latest"}
              >{alias}</span
            >
          {/each}
        </div>
        <div class="fact-row">
          <span class="fact type-chip">{record.type}</span>
          <span class="dot">·</span>
          <span class="fact"
            >{(record.manifest || []).length}
            {(record.manifest || []).length === 1 ? "file" : "files"}</span
          >
          <span class="dot">·</span>
          <span class="fact">{formatSize(record.size_bytes)}</span>
        </div>
        <div class="use-snippet">
          <code class="snippet"><span class="tok-mod">trackio</span><span
              class="tok-punc">.</span><span class="tok-fn">use_artifact</span><span
              class="tok-punc">(</span><span class="tok-str"
              >"{record.name}:v{record.version}"</span><span class="tok-punc"
              >)</span></code>
          <button
            class="copy-btn"
            onclick={() => copy(usageSnippet, "use")}
            title="Copy usage snippet"
          >
            {copied === "use" ? "Copied" : "Copy"}
          </button>
        </div>
      </header>

      <Accordion label="Overview">
        <div class="detail-grid">
          {#if record.description}
            <span class="detail-key">Description</span>
            <span class="detail-val">{record.description}</span>
          {/if}
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
          <span class="detail-key">Created</span>
          <span class="detail-val">{formatDate(record.created_at)}</span>
          <span class="detail-key">Digest</span>
          <span class="detail-val digest-val">
            <span class="mono digest-text" title={record.manifest_digest}
              >{record.manifest_digest?.slice(0, 16)}…</span
            >
            <button
              class="copy-btn small"
              onclick={() => copy(record.manifest_digest, "digest")}
              title="Copy digest"
            >
              {copied === "digest" ? "Copied" : "Copy"}
            </button>
          </span>
        </div>
      </Accordion>

      {#if record.metadata && Object.keys(record.metadata).length}
        <Accordion label="Metadata ({Object.keys(record.metadata).length})">
          <div class="meta-grid">
            {@render metaRows(Object.entries(record.metadata), 0)}
          </div>
        </Accordion>
      {/if}

      <Accordion label="Files ({(record.manifest || []).length})">
        {@render fileTable()}
      </Accordion>
    {/if}
  </div>
{:else}
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
        <span class="detail-val mono"
          >{record.manifest_digest?.slice(0, 16)}…</span
        >
        {#if record.metadata && Object.keys(record.metadata).length}
          {#each Object.entries(record.metadata) as [k, v]}
            <span class="detail-key">{k}</span>
            <span class="detail-val"
              >{typeof v === "object" ? JSON.stringify(v) : String(v)}</span
            >
          {/each}
        {/if}
      </div>
      {@render fileTable()}
    {/if}
  </div>
{/if}

<style>
  .version-detail {
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    padding: 10px 14px 12px;
    background: var(--background-fill-secondary, #f9fafb);
  }

  .panel {
    padding: 4px 4px 24px;
  }
  .panel-header {
    border-bottom: 1px solid var(--border-color-primary, #e5e7eb);
    padding-bottom: 14px;
    margin-bottom: 16px;
  }
  .title-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .art-name {
    font-size: 18px;
    font-weight: 700;
    color: var(--body-text-color, #1f2937);
    margin: 0;
    word-break: break-word;
  }
  .ver-badge {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-sm, 12px);
    font-weight: 600;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f3f4f6);
    border-radius: var(--radius-sm, 4px);
    padding: 2px 7px;
  }
  .fact-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }
  .fact {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .type-chip {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
  }
  .dot {
    color: var(--body-text-color-subdued, #9ca3af);
  }
  .use-snippet {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    background: var(--background-fill-secondary, #f9fafb);
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    padding: 6px 6px 6px 10px;
    width: fit-content;
    max-width: min(480px, 100%);
    overflow: hidden;
  }
  .use-snippet code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    white-space: nowrap;
    overflow-x: auto;
    flex: 1 1 auto;
  }
  .tok-mod {
    color: var(--body-text-color, #1f2937);
  }
  .tok-fn {
    color: #8957e5;
  }
  .tok-str {
    color: #1a7f37;
  }
  .tok-punc {
    color: var(--body-text-color-subdued, #6b7280);
  }
  .copy-btn {
    flex-shrink: 0;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    background: var(--background-fill-primary, #fff);
    color: var(--body-text-color, #374151);
    border-radius: var(--radius-sm, 4px);
    padding: 3px 10px;
    font-size: var(--text-xs, 11px);
    cursor: pointer;
  }
  .copy-btn:hover {
    border-color: var(--color-accent, #f97316);
    color: var(--color-accent, #f97316);
  }
  .copy-btn.small {
    padding: 1px 8px;
  }

  .detail-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 16px;
    margin-bottom: 10px;
    align-items: start;
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
  .digest-val {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .digest-text {
    word-break: break-all;
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

  .meta-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 6px 16px;
    align-items: start;
  }
  .meta-group {
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
  }

  .file-table {
    display: flex;
    flex-direction: column;
  }
  .file-entry {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px 8px;
    margin: 0 -8px;
    border-radius: var(--radius-sm, 4px);
    border-top: 1px solid var(--border-color-primary, #e5e7eb);
    color: inherit;
    text-decoration: none;
    cursor: pointer;
  }
  .file-entry:first-child {
    border-top: none;
  }
  .file-entry:hover {
    background: var(--background-fill-secondary, #f9fafb);
    border-top-color: transparent;
  }
  .spacer {
    flex: 1 1 auto;
  }
  .file-path {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    word-break: break-all;
  }
  .file-digest {
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #9ca3af);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .file-size {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    white-space: nowrap;
  }
  .download-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    color: var(--body-text-color-subdued, #9ca3af);
    transition: color 0.15s;
  }
  .file-entry:hover .download-icon {
    color: var(--color-accent, #f97316);
  }
  .status {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    padding: 4px 0;
  }

  .alias-pill {
    font-size: var(--text-xs, 11px);
    padding: 1px 7px;
    border-radius: 9px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-secondary, #f3f4f6);
    white-space: nowrap;
  }
  .alias-pill.latest {
    color: var(--color-accent, #f97316);
    border-color: var(--color-accent, #f97316);
    background: transparent;
  }
</style>
