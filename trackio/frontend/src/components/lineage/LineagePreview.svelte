<script>
  import { openRunDetail } from "../../lib/router.js";
  import { formatSize } from "../../lib/format.js";

  let { node = null, focusId = null, onOpenVersion = null, onClose = () => {} } =
    $props();

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
</script>

{#if node}
  <div class="preview">
    <div class="preview-header">
      {#if node.kind === "artifact"}
        <span class="title">{node.artifact_name}</span>
        <span class="ver-badge">v{node.version}</span>
        {#each node.aliases as alias}
          <span class="alias-pill" class:latest={alias === "latest"}
            >{alias}</span
          >
        {/each}
      {:else}
        <span class="title">{node.run_name ?? node.run_id}</span>
        <span class="kind-chip run">run</span>
      {/if}
      <span class="spacer"></span>
      <button class="close-btn" title="Close preview" onclick={onClose}
        >×</button
      >
    </div>
    <div class="detail-grid">
      {#if node.kind === "artifact"}
        <span class="detail-key">Type</span>
        <span class="detail-val type-chip">{node.artifact_type}</span>
        <span class="detail-key">Size</span>
        <span class="detail-val">{formatSize(node.size_bytes)}</span>
        <span class="detail-key">Files</span>
        <span class="detail-val">{node.num_files}</span>
        <span class="detail-key">Created</span>
        <span class="detail-val">{formatDate(node.created_at)}</span>
        {#if node.producer_run_name}
          <span class="detail-key">Produced by</span>
          <span class="detail-val">
            <button
              class="run-link"
              onclick={() =>
                openRunDetail(node.producer_run_name, node.producer_run_id)}
              >{node.producer_run_name}</button
            >
          </span>
        {/if}
      {:else}
        <span class="detail-key">First linked</span>
        <span class="detail-val">{formatDate(node.created_at)}</span>
      {/if}
    </div>
    <div class="preview-footer">
      {#if node.kind === "artifact"}
        {#if onOpenVersion && node.id !== focusId}
          <button
            class="open-btn"
            onclick={() => onOpenVersion(node.artifact_name, node.version)}
            >Open version</button
          >
        {/if}
      {:else}
        <button
          class="open-btn"
          onclick={() => openRunDetail(node.run_name, node.run_id)}
          >Open run</button
        >
      {/if}
    </div>
  </div>
{/if}

<style>
  .preview {
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-secondary, #f9fafb);
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .preview-header {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
  }
  .title {
    font-size: var(--text-md, 14px);
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
  }
  .ver-badge {
    font-size: var(--text-xs, 11px);
    font-weight: 600;
    padding: 1px 7px;
    border-radius: 9px;
    color: var(--color-accent, #f97316);
    border: 1px solid var(--color-accent, #f97316);
  }
  .alias-pill {
    font-size: var(--text-xs, 11px);
    padding: 1px 7px;
    border-radius: 9px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-primary, #ffffff);
    white-space: nowrap;
  }
  .alias-pill.latest {
    color: var(--color-accent, #f97316);
  }
  .kind-chip {
    font-size: var(--text-xs, 11px);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    color: #10b981;
  }
  .spacer {
    flex: 1;
  }
  .close-btn {
    background: none;
    border: none;
    color: var(--body-text-color-subdued, #6b7280);
    font-size: 16px;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
  }
  .detail-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 4px 16px;
    align-items: baseline;
  }
  .detail-key {
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #6b7280);
    white-space: nowrap;
  }
  .detail-val {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    overflow-wrap: anywhere;
  }
  .type-chip {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
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
  .preview-footer:empty {
    display: none;
  }
  .open-btn {
    font-size: var(--text-sm, 12px);
    padding: 4px 12px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, #ffffff);
    color: var(--body-text-color, #1f2937);
    cursor: pointer;
  }
  .open-btn:hover {
    border-color: var(--color-accent, #f97316);
    color: var(--color-accent, #f97316);
  }
</style>
