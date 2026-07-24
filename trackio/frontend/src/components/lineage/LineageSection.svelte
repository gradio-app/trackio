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
      selectedId = `art:${versionId}`;
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
    <div class="graph-row">
      <div class="graph-cell">
        <div class="graph-wrap">
          <LineageGraph
            {layout}
            {focusId}
            {selectedId}
            {smooth}
            onSelect={select}
          />
        </div>
        <div class="legend">
          <span class="legend-item"
            ><span class="swatch artifact"></span>Artifact</span
          >
          <span class="legend-item"><span class="swatch run"></span>Run</span>
          <span class="legend-item"
            ><span class="swatch cluster"></span>Cluster</span
          >
          <span class="hint"
            >Drag to pan · Ctrl/Cmd + scroll to zoom · Click a node for details</span
          >
        </div>
      </div>
      {#if selectedNode}
        <div class="side-panel">
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
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .graph-row {
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: stretch;
    gap: 8px;
  }
  .graph-cell {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .graph-wrap {
    flex: 1;
    min-height: 0;
  }
  .side-panel {
    width: 280px;
    flex-shrink: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .side-panel > :global(*) {
    max-height: 100%;
    min-height: 0;
    overflow-y: auto;
    box-sizing: border-box;
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
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
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
    border-color: #3b82f6;
  }
  .swatch.run {
    border-color: #10b981;
  }
  .swatch.cluster {
    border-color: var(--body-text-color-subdued, #6b7280);
    border-style: dashed;
  }
  .hint {
    margin-left: auto;
  }
</style>
