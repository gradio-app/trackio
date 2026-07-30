<script>
  import AliasPill from "../AliasPill.svelte";
  import SearchBox from "../SearchBox.svelte";
  import { openRunDetail } from "../../lib/router.js";
  import { formatDate, formatSize } from "../../lib/format.js";
  import { lineageNodeLabel } from "../../lib/lineage.js";

  let {
    node = null,
    focusId = null,
    onOpenVersion = null,
    onExtract = () => {},
    onExtractAll = () => {},
    onClose = () => {},
  } = $props();

  const EXPAND_ALL_LIMIT = 30;

  let memberQuery = $state("");

  $effect(() => {
    node?.id;
    memberQuery = "";
  });

  const filteredMembers = $derived.by(() => {
    if (node?.kind !== "cluster") return [];
    const query = memberQuery.toLowerCase();
    return node.members.filter((m) =>
      lineageNodeLabel(m).toLowerCase().includes(query),
    );
  });
</script>

{#if node}
  <div class="preview">
    <div class="preview-header">
      {#if node.kind === "artifact"}
        <span class="kind-chip artifact">{node.artifact_type}</span>
        <span class="title">{node.artifact_name}</span>
        <span class="ver-badge">v{node.version}</span>
        {#each node.aliases as alias}
          <AliasPill {alias} />
        {/each}
      {:else if node.kind === "cluster"}
        <span class="kind-chip cluster">cluster</span>
        <span class="title">{lineageNodeLabel(node)}</span>
      {:else}
        <span class="kind-chip run">run</span>
        <span class="title">{node.run_name ?? node.run_id}</span>
      {/if}
      <button class="close-btn" title="Close preview" onclick={onClose}
        >×</button
      >
    </div>
    {#if node.kind === "cluster"}
      <div class="cluster-body">
        <SearchBox
          bind:value={memberQuery}
          placeholder="Search {node.member_kind === 'run'
            ? 'runs'
            : 'versions'}…"
        />
        <ul class="member-list">
          {#each filteredMembers as member (member.id)}
            <li class="member-item">
              <button
                class="member-row"
                title="Show in graph"
                onclick={() => onExtract(member.id)}
              >
                {lineageNodeLabel(member)}
              </button>
            </li>
          {:else}
            <li class="member-empty">No matches.</li>
          {/each}
        </ul>
        {#if node.count <= EXPAND_ALL_LIMIT}
          <button
            class="open-btn"
            onclick={() => onExtractAll(node.members.map((m) => m.id))}
            >Show all</button
          >
        {/if}
      </div>
    {/if}
    <div class="detail-grid">
      {#if node.kind === "artifact"}
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
      {:else if node.kind === "run"}
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
      {:else if node.kind === "run"}
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
    position: relative;
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 6px;
    padding-right: 24px;
  }
  .title {
    font-size: var(--text-md, 14px);
    font-weight: 600;
    color: var(--body-text-color, #1f2937);
  }
  .ver-badge {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: var(--text-sm, 12px);
    font-weight: 600;
    color: var(--body-text-color-subdued, #6b7280);
    background: var(--background-fill-primary, #ffffff);
    border-radius: var(--radius-sm, 4px);
    padding: 2px 7px;
  }
  .kind-chip {
    flex-basis: 100%;
    font-size: var(--text-xs, 11px);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    color: var(--lineage-run);
  }
  .kind-chip.cluster {
    color: var(--body-text-color-subdued, #6b7280);
  }
  .kind-chip.artifact {
    color: var(--lineage-artifact);
  }
  .cluster-body {
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .member-list {
    list-style: none;
    margin: 0;
    padding: 0;
    min-height: 0;
    overflow-y: auto;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, #ffffff);
  }
  .member-item + .member-item {
    border-top: 1px solid var(--border-color-primary, #f3f4f6);
  }
  .member-row {
    display: block;
    width: 100%;
    background: none;
    border: none;
    text-align: left;
    padding: 5px 8px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color, #1f2937);
    overflow-wrap: anywhere;
    cursor: pointer;
  }
  .member-row:hover,
  .member-row:focus-visible {
    background: var(--background-fill-secondary, #f3f4f6);
  }
  .member-empty {
    padding: 6px 8px;
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .close-btn {
    position: absolute;
    top: 0px;
    right: 0;
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
