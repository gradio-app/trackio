<script>
  import { getArtifactLineage } from "../../lib/api.js";
  import { clusterLineage } from "../../lib/lineage.js";
  import { layoutLineage, SMOOTH_EDGE_LIMIT } from "../../lib/lineageLayout.js";
  import LineageGraph from "./LineageGraph.svelte";
  import LineagePreview from "./LineagePreview.svelte";

  let { project = null, versionId = null, onOpenVersion = null } = $props();

  let graph = $state(null);
  let loading = $state(true);
  let error = $state(false);
  let extracted = $state(new Set());
  let selectedId = $state(null);

  const focusId = $derived(`art:${versionId}`);

  $effect(() => {
    loadGraph();
  });

  async function loadGraph() {
    if (!project || versionId == null) {
      loading = false;
      return;
    }
    loading = true;
    error = false;
    extracted = new Set();
    selectedId = null;
    try {
      graph = await getArtifactLineage(project, versionId);
      selectedId = focusId;
    } catch {
      error = true;
    } finally {
      loading = false;
    }
  }

  const clustered = $derived(
    graph ? clusterLineage(graph, focusId, { extracted }) : null,
  );
  const layout = $derived(
    clustered && clustered.nodes.length
      ? layoutLineage(clustered.nodes, clustered.edges)
      : null,
  );
  const smooth = $derived(
    !clustered || clustered.nodes.length <= SMOOTH_EDGE_LIMIT,
  );
  const selectedNode = $derived(
    clustered && selectedId
      ? (clustered.nodes.find((n) => n.id === selectedId) ?? null)
      : null,
  );

  function extract(nodeId) {
    const next = new Set(extracted);
    next.add(nodeId);
    extracted = next;
    selectedId = nodeId;
  }

  function extractAll(nodeIds) {
    const next = new Set(extracted);
    for (const id of nodeIds) next.add(id);
    extracted = next;
    selectedId = null;
  }

  function select(nodeId) {
    selectedId = selectedId === nodeId ? null : nodeId;
  }
</script>

{#if loading}
  <div class="status">Loading lineage…</div>
{:else if error}
  <div class="status">Failed to load lineage.</div>
{:else if !graph || graph.edges.length === 0}
  <div class="status">No lineage recorded for this version.</div>
{:else}
  <div class="lineage">
    {#if graph.truncated}
      <div class="toolbar">
        <span class="notice">Large graph — lineage was truncated.</span>
      </div>
    {:else if clustered.nodes.length > SMOOTH_EDGE_LIMIT}
      <div class="toolbar">
        <span class="notice">
          Large graph — showing {clustered.nodes.length} nodes.
        </span>
      </div>
    {/if}
    <div class="graph-wrap">
        <LineageGraph
          {layout}
          {focusId}
          {selectedId}
          {smooth}
          onSelect={select}
        />
        <div class="legend">
          <span class="legend-item"
            ><svg class="target-swatch" viewBox="-7 -7 14 14" aria-hidden="true"
              ><circle class="target-ring" r="5" /><circle
                class="target-dot"
                r="2"
              /></svg
            >Base Artifact</span
          >
          <span class="legend-item"
            ><span class="swatch artifact"></span>Artifact</span
          >
          <span class="legend-item"><span class="swatch run"></span>Run</span>
        </div>
        <span class="hint"
          >Drag to pan · Ctrl/Cmd + scroll to zoom · Click a node for details</span
        >
        {#if selectedNode}
          <div class="preview-overlay">
            <LineagePreview
              node={selectedNode}
              {focusId}
              {onOpenVersion}
              onExtract={extract}
              onExtractAll={extractAll}
              onClose={() => (selectedId = null)}
            />
          </div>
        {/if}
    </div>
  </div>
{/if}

<style>
  .status {
    font-size: var(--text-sm, 12px);
    color: var(--body-text-color-subdued, #6b7280);
    padding: 6px 0;
  }
  .lineage {
    --lineage-run: #10b981;
    --lineage-artifact: #3b82f6;
    --lineage-selected: #8b5cf6;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .graph-wrap {
    flex: 1;
    min-height: 0;
    position: relative;
  }
  .preview-overlay {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 5;
    width: 280px;
    max-width: calc(100% - 16px);
    max-height: calc(100% - 16px);
    overflow-y: auto;
  }
  .preview-overlay > :global(*) {
    box-sizing: border-box;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 18px;
  }
  .notice {
    font-size: var(--text-xs, 11px);
    color: var(--color-accent, #f97316);
  }
  .legend {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 4;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .hint {
    position: absolute;
    bottom: 8px;
    right: 8px;
    z-index: 4;
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #6b7280);
  }
  .legend-item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 3px;
    background: var(--background-fill-primary, #ffffff);
    border: 1.5px solid;
  }
  .swatch.artifact {
    border-color: var(--lineage-artifact);
  }
  .swatch.run {
    border-color: var(--lineage-run);
  }
  .target-swatch {
    width: 11px;
    height: 11px;
  }
  .target-swatch .target-ring {
    fill: none;
    stroke: var(--color-accent, #f97316);
    stroke-width: 2;
  }
  .target-swatch .target-dot {
    fill: var(--color-accent, #f97316);
  }
</style>
