import * as dagre from "@dagrejs/dagre";

export const NODE_W = 140;
export const NODE_H = 44;
export const SMOOTH_EDGE_LIMIT = 300;
export const EDGE_NODE_GAP = 6;

function shiftPoint(from, toward, gap) {
  const dx = toward.x - from.x;
  const dy = toward.y - from.y;
  const len = Math.hypot(dx, dy);
  if (!len || len <= gap) return from;
  return { x: from.x + (dx / len) * gap, y: from.y + (dy / len) * gap };
}

function trimEdgePoints(points, gap = EDGE_NODE_GAP) {
  if (!points || points.length < 2) return points ?? [];
  const out = points.slice();
  out[0] = shiftPoint(out[0], out[1], gap);
  out[out.length - 1] = shiftPoint(
    out[out.length - 1],
    out[out.length - 2],
    gap,
  );
  return out;
}

export function mergeBidirectionalEdges(edges) {
  const byPair = new Map();
  for (const edge of edges) {
    const pair = [edge.source, edge.target].sort().join("|");
    if (!byPair.has(pair)) byPair.set(pair, []);
    byPair.get(pair).push(edge);
  }
  const merged = [];
  for (const group of byPair.values()) {
    const output = group.find((e) => e.direction === "output");
    const input = group.find((e) => e.direction === "input");
    if (output && input) {
      merged.push({ ...output, bidirectional: true });
    } else {
      merged.push(...group.map((e) => ({ ...e, bidirectional: false })));
    }
  }
  return merged;
}

export function layoutLineage(nodes, edges) {
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setGraph({
    rankdir: "LR",
    nodesep: 14,
    ranksep: 40,
    edgesep: 8,
    marginx: 20,
    marginy: 20,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  const nodeIds = new Set(nodes.map((n) => n.id));
  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_W, height: NODE_H });
  }
  const merged = mergeBidirectionalEdges(
    edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)),
  );
  for (const edge of merged) {
    graph.setEdge(
      edge.source,
      edge.target,
      {},
      `${edge.source}|${edge.target}|${edge.direction}`,
    );
  }

  dagre.layout(graph);

  const outNodes = nodes.map((node) => {
    const pos = graph.node(node.id);
    return { ...node, x: pos.x, y: pos.y, width: NODE_W, height: NODE_H };
  });
  const outEdges = merged.map((edge) => {
    const label = graph.edge(
      edge.source,
      edge.target,
      `${edge.source}|${edge.target}|${edge.direction}`,
    );
    return { ...edge, points: trimEdgePoints(label?.points ?? []) };
  });
  const size = graph.graph();
  return {
    nodes: outNodes,
    edges: outEdges,
    width: size.width ?? 0,
    height: size.height ?? 0,
  };
}

export function edgePath(points, smooth = true) {
  if (!points || points.length === 0) return "";
  const [first, ...rest] = points;
  if (!smooth || points.length < 3) {
    return (
      `M ${first.x} ${first.y}` + rest.map((p) => ` L ${p.x} ${p.y}`).join("")
    );
  }
  const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const start = mid(first, points[1]);
  let d = `M ${first.x} ${first.y} L ${start.x} ${start.y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const control = points[i];
    const end = mid(points[i], points[i + 1]);
    d += ` Q ${control.x} ${control.y} ${end.x} ${end.y}`;
  }
  const last = points[points.length - 1];
  d += ` L ${last.x} ${last.y}`;
  return d;
}
