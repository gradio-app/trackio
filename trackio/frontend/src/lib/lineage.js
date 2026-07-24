export const MAX_LINEAGE_NODES = 1000;

export function buildRunOwnership(runs, links = []) {
  const recordIds = new Set();
  const ownersByName = new Map();
  const knownNames = new Set();
  const addOwner = (name, id) => {
    if (!ownersByName.has(name)) ownersByName.set(name, new Set());
    ownersByName.get(name).add(id);
  };
  for (const r of runs) {
    const id = r.id ?? r.run_id ?? r.name ?? null;
    if (id != null) recordIds.add(id);
    const name = r.name ?? null;
    if (name == null) continue;
    knownNames.add(name);
    if (id != null) addOwner(name, id);
  }
  for (const link of links) {
    const name = link.run_name ?? null;
    if (name == null || knownNames.has(name)) continue;
    const id = link.run_id ?? null;
    if (id == null || recordIds.has(id)) continue;
    recordIds.add(id);
    addOwner(name, id);
  }
  return { recordIds, ownersByName };
}

export function canonicalLinkRunId(link, { recordIds, ownersByName }) {
  const runId = link.run_id ?? null;
  if (runId != null && recordIds.has(runId)) return runId;
  const owners = ownersByName.get(link.run_name ?? null);
  return owners && owners.size === 1 ? owners.values().next().value : null;
}

function compareCreatedAt(a, b) {
  const ca = a.created_at ?? "";
  const cb = b.created_at ?? "";
  return ca < cb ? -1 : ca > cb ? 1 : 0;
}

export function buildLineage(tables, runs, versionId) {
  const { artifacts, versions, aliases, links } = tables;
  const focus = `art:${versionId}`;
  const empty = { focus, truncated: false, nodes: [], edges: [] };

  const grouped = new Map();
  for (const link of links) {
    if (link.direction !== "input" && link.direction !== "output") continue;
    const vid = Number(link.artifact_version_id);
    const key = JSON.stringify([
      link.run_id ?? null,
      link.run_name ?? null,
      vid,
      link.direction,
    ]);
    const existing = grouped.get(key);
    if (!existing || compareCreatedAt(link, existing) < 0) {
      grouped.set(key, {
        run_id: link.run_id ?? null,
        run_name: link.run_name ?? null,
        version_id: vid,
        direction: link.direction,
        created_at: link.created_at,
      });
    }
  }
  const linkRows = [...grouped.values()].sort(compareCreatedAt);

  const ownership = buildRunOwnership(runs, linkRows);
  const runMeta = new Map();
  const canonical = [];
  for (const row of linkRows) {
    const runId = canonicalLinkRunId(row, ownership);
    const runKey = runId != null ? `run:${runId}` : `run:name:${row.run_name}`;
    const meta = runMeta.get(runKey);
    if (!meta) {
      runMeta.set(runKey, {
        run_id: runId,
        run_name: row.run_name,
        created_at: row.created_at,
      });
    } else if ((row.created_at ?? "") < (meta.created_at ?? "")) {
      meta.created_at = row.created_at;
    }
    canonical.push({ ...row, run_key: runKey });
  }

  const byVersion = new Map();
  const byRun = new Map();
  for (const row of canonical) {
    if (!byVersion.has(row.version_id)) byVersion.set(row.version_id, []);
    byVersion.get(row.version_id).push(row.run_key);
    if (!byRun.has(row.run_key)) byRun.set(row.run_key, []);
    byRun.get(row.run_key).push(row.version_id);
  }

  const visited = new Set([focus]);
  let truncated = false;
  const queue = [focus];
  while (queue.length) {
    const node = queue.shift();
    const neighbors = node.startsWith("art:")
      ? (byVersion.get(Number(node.slice(4))) ?? [])
      : (byRun.get(node) ?? []).map((v) => `art:${v}`);
    for (const neighbor of neighbors) {
      if (visited.has(neighbor)) continue;
      if (visited.size >= MAX_LINEAGE_NODES) {
        truncated = true;
        break;
      }
      visited.add(neighbor);
      queue.push(neighbor);
    }
    if (truncated) break;
  }

  const versionIds = [...visited]
    .filter((n) => n.startsWith("art:"))
    .map((n) => Number(n.slice(4)))
    .sort((a, b) => a - b);

  const artifactsById = new Map(artifacts.map((a) => [Number(a.id), a]));
  const versionsById = new Map(versions.map((v) => [Number(v.id), v]));
  const aliasesByVersion = new Map();
  for (const alias of [...aliases].sort((a, b) =>
    a.alias < b.alias ? -1 : a.alias > b.alias ? 1 : 0,
  )) {
    const vid = Number(alias.artifact_version_id);
    if (!aliasesByVersion.has(vid)) aliasesByVersion.set(vid, []);
    aliasesByVersion.get(vid).push(alias.alias);
  }

  const nodes = [];
  const hydrated = new Set();
  for (const vid of versionIds) {
    const version = versionsById.get(vid);
    if (!version) continue;
    const art = artifactsById.get(Number(version.artifact_id));
    if (!art) continue;
    hydrated.add(vid);
    let numFiles;
    try {
      const manifest =
        typeof version.manifest === "string"
          ? JSON.parse(version.manifest)
          : version.manifest;
      numFiles = Array.isArray(manifest) ? manifest.length : 0;
    } catch {
      numFiles = 0;
    }
    nodes.push({
      id: `art:${vid}`,
      kind: "artifact",
      version_id: vid,
      artifact_name: art.name,
      artifact_type: art.type,
      version: Number(version.version),
      aliases: aliasesByVersion.get(vid) ?? [],
      size_bytes: Number(version.size_bytes),
      num_files: numFiles,
      created_at: version.created_at,
      producer_run_id: version.producer_run_id ?? null,
      producer_run_name: version.producer_run_name ?? null,
    });
  }
  if (!hydrated.has(Number(versionId))) return empty;

  const nodeIds = new Set(nodes.map((n) => n.id));
  const runKeys = [...runMeta.keys()]
    .filter((k) => visited.has(k))
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  for (const runKey of runKeys) {
    const meta = runMeta.get(runKey);
    nodeIds.add(runKey);
    nodes.push({
      id: runKey,
      kind: "run",
      run_id: meta.run_id,
      run_name: meta.run_name,
      created_at: meta.created_at,
    });
  }

  const edges = [];
  const seenEdges = new Set();
  for (const row of canonical) {
    const artKey = `art:${row.version_id}`;
    if (!nodeIds.has(artKey) || !nodeIds.has(row.run_key)) continue;
    const [source, target] =
      row.direction === "output"
        ? [row.run_key, artKey]
        : [artKey, row.run_key];
    const dedupe = `${source}|${target}|${row.direction}`;
    if (seenEdges.has(dedupe)) continue;
    seenEdges.add(dedupe);
    edges.push({
      source,
      target,
      direction: row.direction,
      created_at: row.created_at,
    });
  }

  return { focus, truncated, nodes, edges };
}

function sortNeighborIds(ids, nodesById) {
  return [...ids].sort((a, b) => {
    const na = nodesById.get(a);
    const nb = nodesById.get(b);
    const ca = na?.created_at ?? "";
    const cb = nb?.created_at ?? "";
    if (ca !== cb) return ca < cb ? -1 : 1;
    return a < b ? -1 : a > b ? 1 : 0;
  });
}

export function sliceLineage(graph, focusId, options = {}) {
  const { depth = 2, expanded = new Map() } = options;
  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  if (!nodesById.has(focusId)) {
    return { nodes: [], edges: [], frontier: new Map() };
  }

  const adjacency = new Map();
  const addAdj = (a, b) => {
    if (!adjacency.has(a)) adjacency.set(a, new Set());
    adjacency.get(a).add(b);
  };
  for (const edge of graph.edges) {
    addAdj(edge.source, edge.target);
    addAdj(edge.target, edge.source);
  }

  const visible = new Set([focusId]);
  let level = [focusId];
  for (let d = 0; d < depth; d++) {
    const next = [];
    for (const id of level) {
      for (const neighbor of sortNeighborIds(
        adjacency.get(id) ?? [],
        nodesById,
      )) {
        if (visible.has(neighbor)) continue;
        visible.add(neighbor);
        next.push(neighbor);
      }
    }
    level = next;
  }

  let changed = true;
  while (changed) {
    changed = false;
    for (const [id, count] of expanded) {
      if (!visible.has(id) || !count) continue;
      const neighbors = sortNeighborIds(adjacency.get(id) ?? [], nodesById);
      for (const neighbor of neighbors.slice(0, count)) {
        if (!visible.has(neighbor)) {
          visible.add(neighbor);
          changed = true;
        }
      }
    }
  }

  const upstreamOf = new Map();
  const downstreamOf = new Map();
  for (const edge of graph.edges) {
    if (!upstreamOf.has(edge.target)) upstreamOf.set(edge.target, new Set());
    upstreamOf.get(edge.target).add(edge.source);
    if (!downstreamOf.has(edge.source)) {
      downstreamOf.set(edge.source, new Set());
    }
    downstreamOf.get(edge.source).add(edge.target);
  }

  const frontier = new Map();
  for (const id of visible) {
    const hiddenUp = [...(upstreamOf.get(id) ?? [])].filter(
      (n) => !visible.has(n),
    );
    const hiddenDown = [...(downstreamOf.get(id) ?? [])].filter(
      (n) => !visible.has(n),
    );
    const hidden = new Set([...hiddenUp, ...hiddenDown]);
    if (hidden.size) {
      frontier.set(id, {
        upstream: hiddenUp.length,
        downstream: hiddenDown.length,
        total: hidden.size,
      });
    }
  }

  return {
    nodes: graph.nodes.filter((n) => visible.has(n.id)),
    edges: graph.edges.filter(
      (e) => visible.has(e.source) && visible.has(e.target),
    ),
    frontier,
  };
}
