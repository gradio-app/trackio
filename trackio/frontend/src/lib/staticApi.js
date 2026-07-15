import { readParquet } from "./parquetReader.js";

let config = null;
let metricsData = null;
let systemData = null;
let configsData = null;
let tracesData = null;
let runsData = null;
let settingsData = null;
let fileListData = null;
let artifactData = null;

function resolveUrl(filename) {
  if (config.bucket_id) {
    return `https://huggingface.co/buckets/${config.bucket_id}/resolve/${filename}`;
  }
  return `https://huggingface.co/datasets/${config.dataset_id}/resolve/main/${filename}`;
}

export async function initialize(cfg) {
  config = cfg;
}

export function getReadOnlySource() {
  if (!config || config.mode !== "static") return null;
  if (config.bucket_id) {
    return {
      url: `https://huggingface.co/buckets/${config.bucket_id}`,
    };
  }
  if (!config.dataset_id) return null;
  return {
    url: `https://huggingface.co/datasets/${config.dataset_id}`,
  };
}

async function getMetricsData() {
  if (metricsData) return metricsData;
  metricsData = await readParquet(resolveUrl("metrics.parquet"));
  return metricsData;
}

async function getSystemData() {
  if (systemData) return systemData;
  systemData = await readParquet(resolveUrl("aux/system_metrics.parquet"));
  return systemData;
}

async function getConfigsData() {
  if (configsData) return configsData;
  configsData = await readParquet(resolveUrl("aux/configs.parquet"));
  return configsData;
}

async function getTracesData() {
  if (tracesData) return tracesData;
  tracesData = await readParquet(resolveUrl("aux/traces.parquet"));
  return tracesData;
}

async function getRunsJson() {
  if (runsData) return runsData;
  const resp = await fetch(resolveUrl("runs.json"));
  if (!resp.ok) {
    runsData = [];
    return runsData;
  }
  runsData = await resp.json();
  return runsData;
}

let artifactVersionsPromise = null;

function getArtifactVersions() {
  if (!artifactVersionsPromise) {
    artifactVersionsPromise = readParquet(
      resolveUrl("aux/artifact_versions.parquet"),
    ).catch(() => []);
  }
  return artifactVersionsPromise;
}

async function getArtifactTables() {
  if (artifactData) return artifactData;
  const [artifacts, versions, aliases, links] = await Promise.all([
    readParquet(resolveUrl("aux/artifacts.parquet")).catch(() => []),
    getArtifactVersions(),
    readParquet(resolveUrl("aux/artifact_aliases.parquet")).catch(() => []),
    readParquet(resolveUrl("aux/run_artifact_links.parquet")).catch(() => []),
  ]);
  artifactData = { artifacts, versions, aliases, links };
  return artifactData;
}

async function getSettingsJson() {
  if (settingsData) return settingsData;
  const resp = await fetch(resolveUrl("settings.json"));
  if (!resp.ok) {
    settingsData = {};
    return settingsData;
  }
  settingsData = await resp.json();
  return settingsData;
}

const STRUCTURAL_KEYS = new Set([
  "id",
  "run_id",
  "run_name",
  "timestamp",
  "step",
  "log_id",
  "space_id",
  "created_at",
]);

function parseRows(raw) {
  if (!raw || raw.length === 0) return { rows: [], columns: [] };
  return { rows: raw, columns: Object.keys(raw[0]) };
}

function normalizeRun(run) {
  if (run == null) return { name: null, id: null };
  if (typeof run === "string") return { name: run, id: null };
  return { name: run.name ?? null, id: run.id ?? null };
}

function matchesRun(row, run) {
  const target = normalizeRun(run);
  if (target.id != null && row.run_id != null) {
    return row.run_id === target.id;
  }
  return target.name == null ? true : row.run_name === target.name;
}

export async function getAllProjects() {
  return [config.project];
}

export async function getRunsForProject() {
  const runs = await getRunsJson();
  return runs.map((r) => ({
    id: r.id ?? r.run_id ?? r.name,
    name: r.name,
    created_at: r.created_at ?? null,
    last_step: r.last_step ?? null,
    log_count: r.log_count ?? 0,
  }));
}

export async function getMetricsForRun(_project, run) {
  const raw = await getMetricsData();
  const { rows, columns } = parseRows(raw);
  const metricCols = columns.filter((c) => !STRUCTURAL_KEYS.has(c));

  const runRows = rows.filter((r) => matchesRun(r, run));
  const present = new Set();
  for (const row of runRows) {
    for (const col of metricCols) {
      if (row[col] !== null && row[col] !== undefined) {
        present.add(col);
      }
    }
  }
  return [...present];
}

function isScalarMetricValue(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export async function getLogs(_project, run, options = {}) {
  const raw = await getMetricsData();
  const { rows } = parseRows(raw);
  const runRows = rows.filter((r) => matchesRun(r, run));
  const scalarOnly = options.scalar_only === true;

  return runRows.map((row) => {
    const entry = {};
    for (const [key, value] of Object.entries(row)) {
      if (STRUCTURAL_KEYS.has(key)) continue;
      if (value === null || value === undefined) continue;
      if (scalarOnly) {
        if (isScalarMetricValue(value)) entry[key] = value;
        continue;
      }
      if (
        typeof value === "string" &&
        value.startsWith("{") &&
        value.includes("_type")
      ) {
        try {
          entry[key] = JSON.parse(value);
        } catch {
          entry[key] = value;
        }
      } else {
        entry[key] = value;
      }
    }
    entry.timestamp = row.timestamp;
    entry.step = row.step;
    return entry;
  });
}

function flattenTraceSearchText(trace) {
  const parts = [];

  function visit(value) {
    if (value == null) return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (typeof value === "object") {
      Object.values(value).forEach(visit);
      return;
    }
    parts.push(String(value));
  }

  visit(trace.messages || []);
  visit(trace.metadata || {});
  return parts.join(" ").toLowerCase();
}

function sortTraces(traces, sort) {
  switch (sort) {
    case "step_asc":
      return [...traces].sort((a, b) => (a.step ?? 0) - (b.step ?? 0));
    case "step_desc":
      return [...traces].sort((a, b) => (b.step ?? 0) - (a.step ?? 0));
    case "request_time_asc":
      return [...traces].sort((a, b) => String(a.timestamp || "").localeCompare(String(b.timestamp || "")));
    case "request_time_desc":
    default:
      return [...traces].sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
  }
}

function parseTraceJsonField(value, fallback) {
  if (value == null) return fallback;
  if (typeof value === "string") {
    if (!value) return fallback;
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }
  if (typeof value === "object" && !ArrayBuffer.isView(value) && !(value instanceof ArrayBuffer)) {
    return value;
  }
  let text;
  try {
    const bytes = value instanceof ArrayBuffer ? new Uint8Array(value) : new Uint8Array(value.buffer || value);
    text = new TextDecoder("utf-8").decode(bytes);
  } catch {
    return fallback;
  }
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

export async function getTraceSteps(_project, run) {
  const raw = await getTracesData();
  const counts = new Map();
  for (const row of raw) {
    if (!matchesRun(row, run)) continue;
    const step = row.step;
    counts.set(step, (counts.get(step) || 0) + 1);
  }
  const steps = [...counts.entries()]
    .map(([step, count]) => ({ step, count }))
    .sort((a, b) => (a.step ?? 0) - (b.step ?? 0));
  const total = steps.reduce((acc, item) => acc + item.count, 0);
  return { total, steps };
}

export async function getTraces(_project, run, options = {}) {
  const normalizedRun = normalizeRun(run);
  const raw = await getTracesData();
  const traces = raw.filter((r) => matchesRun(r, run)).map((row) => {
    const trace = {
      id: row.id,
      key: row.key,
      index: row.trace_index,
      run: row.run_name || normalizedRun.name,
      run_id: row.run_id || normalizedRun.id,
      step: row.step,
      timestamp: row.timestamp,
      messages: parseTraceJsonField(row.messages, []),
      metadata: parseTraceJsonField(row.metadata, {}),
    };
    trace._search_text = (row.search_text || `${trace.id} ${trace.key} ${flattenTraceSearchText(trace)}`).toLowerCase();
    return trace;
  });

  let filtered = traces;
  if (options.step != null) {
    filtered = filtered.filter((trace) => trace.step === options.step);
  }
  if (options.search && options.search.trim()) {
    const needle = options.search.trim().toLowerCase();
    filtered = filtered.filter((trace) => trace._search_text.includes(needle));
  }
  filtered = sortTraces(filtered, options.sort || "request_time_desc");
  if (options.offset) {
    filtered = filtered.slice(options.offset);
  }
  if (options.limit != null) {
    filtered = filtered.slice(0, options.limit);
  }

  return filtered.map(({ _search_text, ...trace }) => trace);
}

export async function getProjectSummary() {
  const runs = await getRunsJson();
  const lastSteps = runs.map((r) => r.last_step || 0);
  return {
    project: config.project,
    num_runs: runs.length,
    runs: runs.map((r) => ({
      id: r.id ?? r.run_id ?? r.name,
      name: r.name,
      created_at: r.created_at ?? null,
      last_step: r.last_step ?? null,
      log_count: r.log_count ?? 0,
    })),
    last_activity: lastSteps.length ? Math.max(...lastSteps) : null,
  };
}

export async function getRunSummary(_project, run) {
  const runs = await getRunsJson();
  const target = normalizeRun(run);
  const runMeta = runs.find((r) =>
    target.id != null && (r.id ?? r.run_id ?? r.name) != null
      ? (r.id ?? r.run_id ?? r.name) === target.id
      : r.name === target.name,
  );
  if (!runMeta) {
    return {
      project: config.project,
      run: target.name,
      run_id: target.id,
      num_logs: 0,
      metrics: [],
      config: null,
      last_step: null,
    };
  }

  const metrics = await getMetricsForRun(config.project, run);

  let runConfig = null;
  const cfgRaw = await getConfigsData();
  const { rows: cfgRows } = parseRows(cfgRaw);
  const cfgRow = cfgRows.find((r) =>
    target.id != null && r.run_id != null ? r.run_id === target.id : r.run_name === target.name,
  );
  if (cfgRow) {
    runConfig = {};
    for (const [key, value] of Object.entries(cfgRow)) {
      if (key !== "id" && key !== "run_name" && key !== "created_at") {
        runConfig[key] = value;
      }
    }
  }

  return {
    project: config.project,
    run: runMeta.name,
    run_id: runMeta.id ?? runMeta.run_id ?? runMeta.name,
    num_logs: runMeta.log_count || 0,
    metrics,
    config: runConfig,
    last_step: runMeta.last_step,
  };
}

export async function getAlerts() {
  return [];
}

export async function getSystemMetricsForRun(_project, run) {
  const raw = await getSystemData();
  const { rows, columns } = parseRows(raw);
  const metricCols = columns.filter((c) => !STRUCTURAL_KEYS.has(c));

  const runRows = rows.filter((r) => matchesRun(r, run));
  const present = new Set();
  for (const row of runRows) {
    for (const col of metricCols) {
      if (row[col] !== null && row[col] !== undefined) {
        present.add(col);
      }
    }
  }
  return [...present];
}

export async function getSystemLogs(_project, run) {
  const raw = await getSystemData();
  const { rows } = parseRows(raw);
  const runRows = rows.filter((r) => matchesRun(r, run));

  return runRows.map((row) => {
    const entry = {};
    for (const [key, value] of Object.entries(row)) {
      if (STRUCTURAL_KEYS.has(key)) continue;
      if (value === null || value === undefined) continue;
      entry[key] = value;
    }
    entry.timestamp = row.timestamp;
    return entry;
  });
}

export async function getSnapshot(_project, run, step) {
  const raw = await getMetricsData();
  const { rows } = parseRows(raw);
  let runRows = rows.filter((r) => matchesRun(r, run));

  if (step !== null && step !== undefined) {
    runRows = runRows.filter((r) => r.step === step);
  }

  const result = {};
  for (const row of runRows) {
    for (const [key, value] of Object.entries(row)) {
      if (STRUCTURAL_KEYS.has(key)) continue;
      if (value === null || value === undefined) continue;
      if (!result[key]) result[key] = [];
      result[key].push({
        timestamp: row.timestamp,
        step: row.step,
        value,
      });
    }
  }
  return result;
}

export async function getMetricValues(_project, run, metricName) {
  const raw = await getMetricsData();
  const { rows } = parseRows(raw);
  const runRows = rows.filter((r) => matchesRun(r, run));

  return runRows
    .filter((r) => r[metricName] !== null && r[metricName] !== undefined)
    .map((r) => ({
      timestamp: r.timestamp,
      step: r.step,
      value: r[metricName],
    }));
}

export async function getSettings() {
  const settings = await getSettingsJson();
  return {
    logo_urls: {
      light: "/static/trackio/trackio_logo_type_light_transparent.png",
      dark: "/static/trackio/trackio_logo_type_dark_transparent.png",
    },
    color_palette: settings.color_palette || [],
    plot_order: settings.plot_order || [],
    table_truncate_length: 250,
  };
}

let tabAvailabilityCache = null;

const MEDIA_TYPES = new Set([
  "trackio.image",
  "trackio.video",
  "trackio.audio",
  "trackio.table",
]);

const MARKDOWN_TYPES = new Set(["trackio.markdown"]);

function rowHasScalarMetric(row) {
  for (const [key, value] of Object.entries(row)) {
    if (STRUCTURAL_KEYS.has(key)) continue;
    if (value === null || value === undefined) continue;
    if (isScalarMetricValue(value)) return true;
  }
  return false;
}

function rowHasTypedValue(row, types) {
  for (const [key, value] of Object.entries(row)) {
    if (STRUCTURAL_KEYS.has(key)) continue;
    if (value == null) continue;
    let parsed = value;
    if (typeof parsed === "string" && parsed.startsWith("{") && parsed.includes("_type")) {
      try {
        parsed = JSON.parse(parsed);
      } catch {
        continue;
      }
    }
    if (parsed && typeof parsed === "object" && types.has(parsed._type)) return true;
  }
  return false;
}

export async function getTabAvailability() {
  if (tabAvailabilityCache) return tabAvailabilityCache;

  const [metricsRaw, systemRaw, tracesRaw, files, artifactVersions] =
    await Promise.all([
      getMetricsData().catch(() => []),
      getSystemData().catch(() => []),
      getTracesData().catch(() => []),
      getProjectFiles().catch(() => []),
      getArtifactVersions(),
    ]);

  const metricsRows = (metricsRaw || []);
  let metrics = false;
  let media = false;
  let reports = false;
  for (const row of metricsRows) {
    if (!metrics && rowHasScalarMetric(row)) metrics = true;
    if (!media && rowHasTypedValue(row, MEDIA_TYPES)) media = true;
    if (!reports && rowHasTypedValue(row, MARKDOWN_TYPES)) reports = true;
    if (metrics && media && reports) break;
  }

  tabAvailabilityCache = {
    metrics,
    media,
    reports,
    system: (systemRaw || []).length > 0,
    traces: (tracesRaw || []).length > 0,
    files: (files || []).length > 0,
    artifacts: (artifactVersions || []).length > 0,
  };
  return tabAvailabilityCache;
}

const ARTIFACT_VERSION_SPEC_RE = /^v(\d+)$/;

function aliasesByVersionId(aliases) {
  const map = new Map();
  for (const row of aliases) {
    const versionId = Number(row.artifact_version_id);
    if (!map.has(versionId)) map.set(versionId, []);
    map.get(versionId).push(row.alias);
  }
  return map;
}

function compareCreatedAt(a, b) {
  return String(a.created_at || "").localeCompare(String(b.created_at || ""));
}

export async function listArtifacts() {
  const { artifacts, versions, aliases } = await getArtifactTables();
  const aliasMap = aliasesByVersionId(aliases);
  const versionsByArtifact = new Map();
  for (const row of versions) {
    const artifactId = Number(row.artifact_id);
    if (!versionsByArtifact.has(artifactId)) {
      versionsByArtifact.set(artifactId, []);
    }
    versionsByArtifact.get(artifactId).push({
      version_id: Number(row.id),
      version: Number(row.version),
      aliases: aliasMap.get(Number(row.id)) || [],
      size_bytes: Number(row.size_bytes),
      created_at: row.created_at,
    });
  }
  for (const entries of versionsByArtifact.values()) {
    entries.sort((a, b) => b.version - a.version);
  }
  return [...artifacts]
    .sort((a, b) => {
      if (a.type !== b.type) return a.type < b.type ? -1 : 1;
      if (a.name !== b.name) return a.name < b.name ? -1 : 1;
      return 0;
    })
    .map((art) => {
      const artVersions = versionsByArtifact.get(Number(art.id)) || [];
      return {
        name: art.name,
        type: art.type,
        description: art.description ?? null,
        created_at: art.created_at,
        num_versions: artVersions.length,
        latest_version: artVersions.length ? artVersions[0].version : null,
        versions: artVersions,
      };
    });
}

export async function getArtifactManifest(_project, name, spec) {
  const { artifacts, versions, aliases } = await getArtifactTables();
  const art = artifacts.find((a) => a.name === name);
  if (!art) return null;
  const artifactId = Number(art.id);
  const artVersions = versions.filter(
    (v) => Number(v.artifact_id) === artifactId,
  );
  const target = spec || "latest";
  const specMatch = ARTIFACT_VERSION_SPEC_RE.exec(target);
  let row = null;
  if (specMatch) {
    const versionInt = Number(specMatch[1]);
    row = artVersions.find((v) => Number(v.version) === versionInt) || null;
  } else {
    const aliasRow = aliases.find(
      (a) => Number(a.artifact_id) === artifactId && a.alias === target,
    );
    if (aliasRow) {
      row =
        artVersions.find(
          (v) => Number(v.id) === Number(aliasRow.artifact_version_id),
        ) || null;
    }
  }
  if (!row) return null;
  const aliasMap = aliasesByVersionId(aliases);
  return {
    artifact_id: artifactId,
    version_id: Number(row.id),
    version: Number(row.version),
    name: art.name,
    type: art.type,
    description: art.description ?? null,
    manifest: parseTraceJsonField(row.manifest, []),
    manifest_digest: row.manifest_digest,
    metadata: parseTraceJsonField(row.metadata, null),
    size_bytes: Number(row.size_bytes),
    producer_run_id: row.producer_run_id ?? null,
    producer_run_name: row.producer_run_name ?? null,
    created_at: row.created_at,
    aliases: aliasMap.get(Number(row.id)) || [],
  };
}

async function getLinkOwnership() {
  const runs = await getRunsJson();
  const recordIds = new Set();
  const ownersByName = new Map();
  for (const r of runs) {
    const id = r.id ?? r.run_id ?? r.name ?? null;
    if (id == null) continue;
    recordIds.add(id);
    const name = r.name ?? null;
    if (name == null) continue;
    if (!ownersByName.has(name)) ownersByName.set(name, new Set());
    ownersByName.get(name).add(id);
  }
  return { recordIds, ownersByName };
}

function canonicalLinkRunId(link, { recordIds, ownersByName }) {
  const runId = link.run_id ?? null;
  if (runId != null && recordIds.has(runId)) return runId;
  const owners = ownersByName.get(link.run_name ?? null);
  return owners && owners.size === 1 ? owners.values().next().value : null;
}

export async function getRunArtifacts(_project, run) {
  const result = { input: [], output: [] };
  const target = normalizeRun(run);
  if (target.name == null && target.id == null) return result;
  const { artifacts, versions, links } = await getArtifactTables();
  const ownership = await getLinkOwnership();
  const versionsById = new Map(versions.map((v) => [Number(v.id), v]));
  const artifactsById = new Map(artifacts.map((a) => [Number(a.id), a]));
  const runLinks = links
    .filter((l) =>
      target.id != null
        ? canonicalLinkRunId(l, ownership) === target.id
        : matchesRun(l, run),
    )
    .sort(compareCreatedAt);
  const seen = new Set();
  for (const link of runLinks) {
    const version = versionsById.get(Number(link.artifact_version_id));
    if (!version) continue;
    const art = artifactsById.get(Number(version.artifact_id));
    if (!art || !result[link.direction]) continue;
    const dedupeKey = `${link.direction}:${Number(version.id)}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    result[link.direction].push({
      version_id: Number(version.id),
      name: art.name,
      type: art.type,
      version: Number(version.version),
      size_bytes: Number(version.size_bytes),
      created_at: link.created_at,
    });
  }
  return result;
}

export async function getRunArtifactCounts() {
  const { links } = await getArtifactTables();
  const ownership = await getLinkOwnership();
  const byKey = new Map();
  const seenByKey = new Map();
  for (const link of links) {
    const runId = canonicalLinkRunId(link, ownership);
    const runName = link.run_name ?? null;
    const key = JSON.stringify([runId, runName]);
    if (!byKey.has(key)) {
      byKey.set(key, { run_id: runId, run_name: runName, input: 0, output: 0 });
      seenByKey.set(key, new Set());
    }
    const seen = seenByKey.get(key);
    const linkKey = `${link.direction}:${Number(link.artifact_version_id)}`;
    if (seen.has(linkKey)) continue;
    seen.add(linkKey);
    const entry = byKey.get(key);
    if (link.direction === "input" || link.direction === "output") {
      entry[link.direction] += 1;
    }
  }
  return [...byKey.values()];
}

export async function getArtifactConsumers(_project, versionId) {
  const { links } = await getArtifactTables();
  return links
    .filter(
      (l) =>
        l.direction === "input" &&
        Number(l.artifact_version_id) === Number(versionId),
    )
    .sort(compareCreatedAt)
    .map((l) => ({
      run_name: l.run_name ?? null,
      run_id: l.run_id ?? null,
      created_at: l.created_at,
    }));
}

export function getArtifactBlobUrl(_project, digest) {
  return resolveUrl(`artifacts/blobs/sha256/${digest.slice(0, 2)}/${digest}`);
}

export async function getProjectFiles() {
  if (fileListData) return fileListData;

  if (config.bucket_id) {
    const resp = await fetch(
      `https://huggingface.co/api/buckets/${config.bucket_id}/tree?prefix=media/files/&recursive=true`,
    );
    if (!resp.ok) {
      fileListData = [];
      return fileListData;
    }
    const entries = await resp.json();
    fileListData = (Array.isArray(entries) ? entries : [])
      .filter((e) => e.type === "file")
      .map((e) => ({
        name: e.path.split("/").at(-1) ?? e.path,
        path: e.path.slice("media/".length),
      }));
    return fileListData;
  }

  const resp = await fetch(
    `https://huggingface.co/api/datasets/${config.dataset_id}`,
  );
  if (!resp.ok) {
    fileListData = [];
    return fileListData;
  }
  const info = await resp.json();
  const siblings = Array.isArray(info?.siblings) ? info.siblings : [];
  fileListData = siblings
    .map((entry) => entry?.rfilename)
    .filter((name) => typeof name === "string" && name.startsWith("media/files/"))
    .map((name) => ({
      name: name.split("/").at(-1) ?? name,
      path: name.slice("media/".length),
    }));
  return fileListData;
}

export async function getRunConfigs() {
  const CONFIG_STRUCTURAL_KEYS = new Set(["id", "run_id", "run_name", "created_at"]);
  const cfgRaw = await getConfigsData().catch(() => null);
  if (!cfgRaw) return {};
  const { rows } = parseRows(cfgRaw);
  const result = {};
  for (const row of rows) {
    const runName = row.run_name;
    if (!runName) continue;
    const cfg = {};
    for (const [key, value] of Object.entries(row)) {
      if (CONFIG_STRUCTURAL_KEYS.has(key)) continue;
      if (value !== null && value !== undefined) cfg[key] = value;
    }
    result[row.run_id ?? runName] = cfg;
  }
  return result;
}

export async function getRunMutationStatus() {
  return { allowed: false };
}

export async function deleteRun() {
  throw new Error("Not supported in static mode");
}

export async function renameRun() {
  throw new Error("Not supported in static mode");
}

function stripProjectPrefix(path) {
  if (config.project && path.startsWith(config.project + "/")) {
    return path.slice(config.project.length + 1);
  }
  return path;
}

const blobCache = new Map();

export async function fetchMediaBlob(path) {
  const relative = stripProjectPrefix(path);
  const url = resolveUrl(`media/${relative}`);
  if (blobCache.has(url)) return blobCache.get(url);

  const resp = await fetch(url);
  if (!resp.ok) return url;
  const blob = await resp.blob();
  const blobUrl = URL.createObjectURL(blob);
  blobCache.set(url, blobUrl);
  return blobUrl;
}

export function getAssetUrl(path) {
  const relative = stripProjectPrefix(path);
  return resolveUrl(`media/${relative}`);
}

export function getMediaUrl(path) {
  const relative = stripProjectPrefix(path);
  return resolveUrl(`media/${relative}`);
}
