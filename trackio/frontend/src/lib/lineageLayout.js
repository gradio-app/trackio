import * as dagre from "@dagrejs/dagre";

export const NODE_W = 140;
export const NODE_H = 44;
export const SMOOTH_EDGE_LIMIT = 300;
export const EDGE_NODE_GAP = 6;

function assignSideAnchors(routed) {
  const groups = new Map();
  const add = (nodeId, endpoint) => {
    const key = `${nodeId}|${endpoint.side}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(endpoint);
  };
  for (const route of routed) {
    add(route.edge.source, route.start);
    add(route.edge.target, route.end);
  }
  for (const endpoints of groups.values()) {
    endpoints.sort((a, b) => a.sortY - b.sortY);
    endpoints.forEach((endpoint, i) => {
      endpoint.y =
        endpoint.node.y -
        NODE_H / 2 +
        (NODE_H * (i + 1)) / (endpoints.length + 1);
    });
  }
}

function anchorPoint(endpoint, gap = EDGE_NODE_GAP) {
  return {
    x: endpoint.node.x + endpoint.side * (NODE_W / 2 + gap),
    y: endpoint.y,
  };
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
    ranksep: 50,
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
  const routed = merged.map((edge) => {
    const label = graph.edge(
      edge.source,
      edge.target,
      `${edge.source}|${edge.target}|${edge.direction}`,
    );
    const source = graph.node(edge.source);
    const target = graph.node(edge.target);
    const interior = (label?.points ?? []).slice(1, -1);
    return {
      edge,
      interior,
      start: {
        node: source,
        side: target.x >= source.x ? 1 : -1,
        sortY: interior[0]?.y ?? target.y,
      },
      end: {
        node: target,
        side: source.x >= target.x ? 1 : -1,
        sortY: interior[interior.length - 1]?.y ?? source.y,
      },
    };
  });
  assignSideAnchors(routed);
  const outEdges = routed.map(({ edge, interior, start, end }) => ({
    ...edge,
    points: [anchorPoint(start), ...interior, anchorPoint(end)],
  }));
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
