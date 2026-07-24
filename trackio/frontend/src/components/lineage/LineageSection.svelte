<script>
  import { getArtifactLineage } from "../../lib/api.js";
  import { sliceLineage } from "../../lib/lineage.js";
  import { layoutLineage, SMOOTH_EDGE_LIMIT } from "../../lib/lineageLayout.js";
  import LineageGraph from "./LineageGraph.svelte";
  import LineagePreview from "./LineagePreview.svelte";

  let { project = null, versionId = null, onOpenVersion = null } = $props();

  const REVEAL_STEP = 20;
  const DEFAULT_DEPTH = 2;

  let graph = $state(null);
  let loading = $state(true);
  let error = $state(false);
  let expanded = $state(new Map());
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
    try {
      graph = await getArtifactLineage(project, versionId);
    } catch {
      error = true;
    } finally {
      loading = false;
    }
  }

  const sliced = $derived(
    graph ? sliceLineage(graph, focusId, { depth: DEFAULT_DEPTH, expanded }) : null,
  );
  const layout = $derived(
    sliced && sliced.nodes.length
      ? layoutLineage(sliced.nodes, sliced.edges)
      : null,
  );
  const smooth = $derived(!sliced || sliced.nodes.length <= SMOOTH_EDGE_LIMIT);
  const selectedNode = $derived(
    sliced && selectedId
      ? (sliced.nodes.find((n) => n.id === selectedId) ?? null)
      : null,
  );

  function expand(nodeId) {
    const next = new Map(expanded);
    next.set(nodeId, (next.get(nodeId) ?? 0) + REVEAL_STEP);
    expanded = next;
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
    <div class="toolbar">
      <span class="counts">
        {sliced.nodes.length} of {graph.nodes.length}
        {graph.nodes.length === 1 ? "node" : "nodes"} shown
      </span>
      {#if graph.truncated}
        <span class="notice">Large graph — lineage was truncated.</span>
      {:else if sliced.nodes.length > SMOOTH_EDGE_LIMIT}
        <span class="notice">
          Large graph — showing {sliced.nodes.length} nodes.
        </span>
      {/if}
    </div>
    <LineageGraph
      {layout}
      frontier={sliced.frontier}
      {focusId}
      {selectedId}
      {smooth}
      onSelect={select}
      onExpand={expand}
    />
    {#if selectedNode}
      <LineagePreview
        node={selectedNode}
        {focusId}
        {onOpenVersion}
        onClose={() => (selectedId = null)}
      />
    {/if}
    <div class="legend">
      <span class="legend-item"><span class="swatch artifact"></span>Artifact</span>
      <span class="legend-item"><span class="swatch run"></span>Run</span>
      <span class="hint">Drag to pan · Ctrl/Cmd + scroll to zoom · Click a node for details</span>
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
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 18px;
  }
  .counts {
    font-size: var(--text-xs, 11px);
    color: var(--body-text-color-subdued, #6b7280);
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
  .hint {
    margin-left: auto;
  }
</style>
