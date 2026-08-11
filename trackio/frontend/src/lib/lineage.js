export const MAX_LINEAGE_NODES = 1000;

export function lineageNodeLabel(node) {
  if (node.kind === "artifact") {
    return `${node.artifact_name}:v${node.version}`;
  }
  if (node.kind === "cluster") {
    return `${node.count} ${node.member_kind === "run" ? "Runs" : "Artifacts"}`;
  }
  return node.run_name ?? node.run_id ?? "run";
}

export function edgeKey(edge) {
  return `${edge.source}|${edge.target}|${edge.direction}`;
}

const numFilesByVersion = new WeakMap();

function versionNumFiles(version) {
  if (numFilesByVersion.has(version)) return numFilesByVersion.get(version);
  let numFiles = 0;
  try {
    const manifest =
      typeof version.manifest === "string"
        ? JSON.parse(version.manifest)
        : version.manifest;
    if (Array.isArray(manifest)) numFiles = manifest.length;
  } catch {
    numFiles = 0;
  }
  numFilesByVersion.set(version, numFiles);
  return numFiles;
}

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
  const runRecordIds = new Set(recordIds);
  for (const link of links) {
    const name = link.run_name ?? null;
    if (name == null || knownNames.has(name)) continue;
    const id = link.run_id ?? null;
    if (id == null || runRecordIds.has(id)) continue;
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
    if (!runMeta.has(runKey)) {
      runMeta.set(runKey, {
        run_id: runId,
        run_name: row.run_name,
        created_at: row.created_at,
      });
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
  for (let head = 0; head < queue.length; head++) {
    const node = queue[head];
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
    nodes.push({
      id: `art:${vid}`,
      kind: "artifact",
      version_id: vid,
      artifact_name: art.name,
      artifact_type: art.type,
      version: Number(version.version),
      aliases: aliasesByVersion.get(vid) ?? [],
      size_bytes: Number(version.size_bytes),
      num_files: versionNumFiles(version),
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
    const edge = {
      source,
      target,
      direction: row.direction,
      created_at: row.created_at,
    };
    const dedupe = edgeKey(edge);
    if (seenEdges.has(dedupe)) continue;
    seenEdges.add(dedupe);
    edges.push(edge);
  }

  return { focus, truncated, nodes, edges };
}

export const CLUSTER_THRESHOLD = 5;

function compareNodes(a, b) {
  const ca = a.created_at ?? "";
  const cb = b.created_at ?? "";
  if (ca !== cb) return ca < cb ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export function clusterLineage(graph, focusId, options = {}) {
  const { threshold = CLUSTER_THRESHOLD, extracted = new Set() } = options;

  const signatures = new Map();
  for (const node of graph.nodes) {
    signatures.set(node.id, []);
  }
  for (const edge of graph.edges) {
    signatures.get(edge.source)?.push(`out:${edge.direction}:${edge.target}`);
    signatures.get(edge.target)?.push(`in:${edge.direction}:${edge.source}`);
  }

  const groups = new Map();
  for (const node of graph.nodes) {
    if (node.id === focusId) continue;
    const signature = `${node.kind}#${signatures.get(node.id).sort().join(",")}`;
    if (!groups.has(signature)) groups.set(signature, []);
    groups.get(signature).push(node);
  }

  const memberOf = new Map();
  const clusters = [];
  for (const [signature, group] of groups) {
    if (group.length < threshold) continue;
    const members = group
      .filter((n) => !extracted.has(n.id))
      .sort(compareNodes);
    if (members.length < 2) continue;
    const cluster = {
      id: `cluster:${signature}`,
      kind: "cluster",
      member_kind: group[0].kind,
      count: members.length,
      members,
      created_at: members[0].created_at,
    };
    clusters.push(cluster);
    for (const member of members) {
      memberOf.set(member.id, cluster.id);
    }
  }

  const nodes = [
    ...graph.nodes.filter((n) => !memberOf.has(n.id)),
    ...clusters.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
  ];

  const edges = [];
  const seen = new Map();
  for (const edge of graph.edges) {
    const mapped = {
      ...edge,
      source: memberOf.get(edge.source) ?? edge.source,
      target: memberOf.get(edge.target) ?? edge.target,
    };
    const key = edgeKey(mapped);
    const existing = seen.get(key);
    if (existing) {
      if ((edge.created_at ?? "") < (existing.created_at ?? "")) {
        existing.created_at = edge.created_at;
      }
      continue;
    }
    seen.set(key, mapped);
    edges.push(mapped);
  }

  return { nodes, edges };
}
