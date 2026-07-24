<script>
  import { edgePath, NODE_H, NODE_W } from "../../lib/lineageLayout.js";

  let {
    layout = null,
    focusId = null,
    selectedId = null,
    smooth = true,
    onSelect = () => {},
  } = $props();

  let container = $state(null);
  let viewWidth = $state(0);
  let viewHeight = $state(0);
  let view = $state({ x: 0, y: 0, k: 1 });
  let fittedFor = null;

  const MIN_ZOOM = 0.25;
  const MAX_ZOOM = 2.5;

  function fit() {
    if (!layout || !viewWidth || !viewHeight) return;
    const k = Math.min(
      viewWidth / Math.max(layout.width, 1),
      viewHeight / Math.max(layout.height, 1),
      1,
    );
    view = {
      k,
      x: (viewWidth - layout.width * k) / 2,
      y: (viewHeight - layout.height * k) / 2,
    };
  }

  $effect(() => {
    if (!layout || !viewWidth || !viewHeight) return;
    if (fittedFor !== focusId) {
      fittedFor = focusId;
      fit();
    }
  });

  function zoomBy(factor, cx = viewWidth / 2, cy = viewHeight / 2) {
    const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.k * factor));
    const scale = k / view.k;
    view = {
      k,
      x: cx - (cx - view.x) * scale,
      y: cy - (cy - view.y) * scale,
    };
  }

  function wheelZoom(node) {
    const handler = (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const rect = node.getBoundingClientRect();
      zoomBy(
        Math.exp(-event.deltaY * 0.002),
        event.clientX - rect.left,
        event.clientY - rect.top,
      );
    };
    node.addEventListener("wheel", handler, { passive: false });
    return { destroy: () => node.removeEventListener("wheel", handler) };
  }

  let panning = $state(null);

  function onPointerDown(event) {
    if (event.button !== 0) return;
    panning = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event) {
    if (!panning) return;
    view = {
      ...view,
      x: view.x + event.clientX - panning.x,
      y: view.y + event.clientY - panning.y,
    };
    panning = { x: event.clientX, y: event.clientY };
  }

  function onPointerUp(event) {
    if (!panning) return;
    panning = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function truncate(text, max = 18) {
    if (text == null) return "";
    const s = String(text);
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  }

  function nodeLabel(node) {
    if (node.kind === "artifact") {
      return `${node.artifact_name}:v${node.version}`;
    }
    if (node.kind === "cluster") {
      return `${node.count} ${node.member_kind === "run" ? "runs" : "artifact versions"}`;
    }
    return node.run_name ?? node.run_id ?? "run";
  }

  function nodeChip(node) {
    if (node.kind === "artifact") return node.artifact_type;
    if (node.kind === "cluster") return "cluster";
    return "run";
  }

  let focusChipWidth = $state(0);

  function measureChip(el) {
    focusChipWidth = el.getComputedTextLength();
  }

  function handleNodeKey(event, node) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(node.id);
    }
  }
</script>

<div
  class="graph-container"
  bind:this={container}
  bind:clientWidth={viewWidth}
  bind:clientHeight={viewHeight}
>
  <svg
    class="graph"
    class:panning
    use:wheelZoom
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
    onpointercancel={onPointerUp}
    role="application"
    aria-label="Artifact lineage graph"
  >
    <defs>
      <marker
        id="lineage-arrow-end"
        viewBox="0 0 10 10"
        refX="6"
        refY="5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path d="M 0 1 L 9 5 L 0 9 Z" class="arrow-head" />
      </marker>
    </defs>
    {#if layout}
      <g transform="translate({view.x}, {view.y}) scale({view.k})">
        {#each layout.edges as edge (`${edge.source}|${edge.target}|${edge.direction}`)}
          <path
            class="edge"
            d={edgePath(edge.points, smooth)}
            marker-end="url(#lineage-arrow-end)"
            marker-start={edge.bidirectional ? "url(#lineage-arrow-end)" : null}
          />
        {/each}
        {#each layout.nodes as node (node.id)}
          <g
            class="node {node.kind} {node.kind === 'cluster'
              ? `cluster-${node.member_kind}`
              : ''}"
            class:focused={node.id === focusId}
            class:selected={node.id === selectedId}
            transform="translate({node.x - NODE_W / 2}, {node.y - NODE_H / 2})"
            role="button"
            tabindex="0"
            aria-label={nodeLabel(node)}
            onpointerdown={(e) => e.stopPropagation()}
            onclick={() => onSelect(node.id)}
            onkeydown={(e) => handleNodeKey(e, node)}
          >
            {#if node.kind === "cluster"}
              <rect
                class="node-box stack"
                x="8"
                y="-8"
                width={NODE_W - 16}
                height={NODE_H}
                rx="6"
              />
              <rect
                class="node-box stack"
                x="4"
                y="-4"
                width={NODE_W - 8}
                height={NODE_H}
                rx="6"
              />
            {/if}
            <rect class="node-box" width={NODE_W} height={NODE_H} rx="6" />
            {#if node.id === focusId}
              <text class="node-chip" x="10" y="16" use:measureChip>
                {truncate(nodeChip(node), 12).toUpperCase()}
              </text>
              <g
                class="base-badge"
                transform="translate({10 + focusChipWidth + 6}, 5.5)"
              >
                <rect width="34" height="14" rx="7" />
                <text x="17" y="10.5" text-anchor="middle">base</text>
              </g>
            {:else}
              <text class="node-chip" x="10" y="16">
                {truncate(nodeChip(node), 20).toUpperCase()}
              </text>
            {/if}
            <text class="node-label" x="10" y="33">
              {node.kind === "cluster"
                ? nodeLabel(node)
                : truncate(nodeLabel(node))}
              <title>{nodeLabel(node)}</title>
            </text>
          </g>
        {/each}
      </g>
    {/if}
  </svg>
  <div class="zoom-controls">
    <button title="Zoom in" onclick={() => zoomBy(1.25)}>+</button>
    <button title="Zoom out" onclick={() => zoomBy(0.8)}>−</button>
    <button title="Fit graph" onclick={fit}>Fit</button>
  </div>
</div>

<style>
  .graph-container {
    --lineage-run: #10b981;
    --lineage-artifact: #3b82f6;
    --lineage-selected: #8b5cf6;
    position: relative;
    height: 100%;
    min-height: 400px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-md, 6px);
    background: var(--background-fill-primary, #ffffff);
    overflow: hidden;
  }
  .graph {
    width: 100%;
    height: 100%;
    display: block;
    cursor: grab;
    touch-action: none;
  }
  .graph.panning {
    cursor: grabbing;
  }
  .edge {
    fill: none;
    stroke: var(--border-color-primary, #d1d5db);
    stroke-width: 1.5;
  }
  .arrow-head {
    fill: var(--border-color-primary, #d1d5db);
  }
  .node {
    cursor: pointer;
    outline: none;
  }
  .node-box {
    fill: var(--background-fill-primary, #ffffff);
    stroke-width: 1.5;
  }
  .node.run .node-box {
    stroke: var(--lineage-run);
  }
  .node.artifact .node-box {
    stroke: var(--lineage-artifact);
  }
  .node.cluster .node-box {
    stroke-dasharray: 4 3;
  }
  .node.cluster-artifact .node-box {
    stroke: var(--lineage-artifact);
  }
  .node.cluster-run .node-box {
    stroke: var(--lineage-run);
  }
  .node.cluster .node-box.stack {
    fill: var(--background-fill-secondary, #f3f4f6);
    stroke-dasharray: none;
    opacity: 0.7;
  }
  .node.selected .node-box,
  .node:focus-visible .node-box {
    stroke: var(--lineage-selected);
    stroke-width: 2.5;
    filter: drop-shadow(0 0 5px rgba(139, 92, 246, 0.65));
  }
  .node.selected .node-box {
    fill: color-mix(
      in srgb,
      var(--lineage-selected) 10%,
      var(--background-fill-primary, #ffffff)
    );
  }
  .base-badge rect {
    fill: var(--background-fill-secondary, #f3f4f6);
    stroke: var(--border-color-primary, #e5e7eb);
    stroke-width: 1;
  }
  .base-badge text {
    font-size: 9px;
    fill: var(--body-text-color-subdued, #6b7280);
  }
  .node-chip {
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.05em;
    fill: var(--body-text-color-subdued, #6b7280);
  }
  .node.run .node-chip,
  .node.cluster-run .node-chip {
    fill: var(--lineage-run);
  }
  .node.artifact .node-chip,
  .node.cluster-artifact .node-chip {
    fill: var(--lineage-artifact);
  }
  .node-label {
    font-size: 12px;
    font-weight: 500;
    fill: var(--body-text-color, #1f2937);
  }
  .zoom-controls {
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex;
    gap: 4px;
  }
  .zoom-controls button {
    min-width: 26px;
    height: 26px;
    padding: 0 7px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
    border-radius: var(--radius-sm, 4px);
    background: var(--background-fill-primary, #ffffff);
    color: var(--body-text-color-subdued, #6b7280);
    font-size: var(--text-sm, 13px);
    cursor: pointer;
  }
  .zoom-controls button:hover {
    color: var(--body-text-color, #1f2937);
    border-color: var(--color-accent, #f97316);
  }
</style>
