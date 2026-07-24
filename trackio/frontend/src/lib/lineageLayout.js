import * as dagre from "@dagrejs/dagre";

export const NODE_W = 140;
export const NODE_H = 44;
export const SMOOTH_EDGE_LIMIT = 300;

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
    return { ...edge, points: label?.points ?? [] };
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
  let d = `M ${first.x} ${first.y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const control = points[i];
    const end =
      i === points.length - 2
        ? points[points.length - 1]
        : {
            x: (points[i].x + points[i + 1].x) / 2,
            y: (points[i].y + points[i + 1].y) / 2,
          };
    d += ` Q ${control.x} ${control.y} ${end.x} ${end.y}`;
  }
  return d;
}
