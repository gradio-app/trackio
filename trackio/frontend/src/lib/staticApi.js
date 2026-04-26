import { readParquet } from "./parquetReader.js";

let config = null;
let metricsData = null;
let systemData = null;
let configsData = null;
let runsData = null;
let settingsData = null;
let fileListData = null;

function resolveUrl(filename) {
  if (config.bucket_id) {
    return `https://huggingface.co/buckets/${config.bucket_id}/resolve/${filename}`;
  }
  return `https://huggingface.co/datasets/${config.dataset_id}/resolve/main/${filename}`;
}

function authHeaders() {
  return {};
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
  metricsData = await readParquet(resolveUrl("metrics.parquet"), authHeaders());
  return metricsData;
}

async function getSystemData() {
  if (systemData) return systemData;
  systemData = await readParquet(
    resolveUrl("aux/system_metrics.parquet"),
    authHeaders(),
  );
  return systemData;
}

async function getConfigsData() {
  if (configsData) return configsData;
  configsData = await readParquet(resolveUrl("aux/configs.parquet"), authHeaders());
  return configsData;
}

async function getRunsJson() {
  if (runsData) return runsData;
  const resp = await fetch(resolveUrl("runs.json"), { headers: authHeaders() });
  if (!resp.ok) {
    runsData = [];
    return runsData;
  }
  runsData = await resp.json();
  return runsData;
}

async function getSettingsJson() {
  if (settingsData) return settingsData;
  const resp = await fetch(resolveUrl("settings.json"), { headers: authHeaders() });
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

export async function getLogs(_project, run) {
  const raw = await getMetricsData();
  const { rows } = parseRows(raw);
  const runRows = rows.filter((r) => matchesRun(r, run));

  return runRows.map((row) => {
    const entry = {};
    for (const [key, value] of Object.entries(row)) {
      if (STRUCTURAL_KEYS.has(key)) continue;
      if (value === null || value === undefined) continue;
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

export async function getTraces(_project, run, options = {}) {
  const logs = await getLogs(_project, run);
  const normalizedRun = normalizeRun(run);
  const runIdent = normalizedRun.id || normalizedRun.name || "run";
  const traces = [];

  function maybeParseStructured(value) {
    if (
      typeof value === "string" &&
      (value.startsWith("{") || value.startsWith("[")) &&
      value.includes("_type")
    ) {
      try {
        return JSON.parse(value);
      } catch {
        return value;
      }
    }
    return value;
  }

  for (const log of logs) {
    for (const [key, value] of Object.entries(log)) {
      if (key === "step" || key === "timestamp") continue;
      const parsedValue = maybeParseStructured(value);
      const candidates = Array.isArray(parsedValue) ? parsedValue : [parsedValue];
      for (let index = 0; index < candidates.length; index += 1) {
        const candidate = candidates[index];
        if (!candidate || typeof candidate !== "object" || candidate._type !== "trackio.trace") {
          continue;
        }
        const traceIndex = Array.isArray(parsedValue) ? index : null;
        const trace = {
          id: `${runIdent}:${log.step}:${key}${traceIndex !== null ? `:${traceIndex}` : ""}`,
          key,
          index: traceIndex,
          run: normalizedRun.name,
          run_id: normalizedRun.id,
          step: log.step,
          timestamp: log.timestamp,
          messages: candidate.messages || [],
          metadata: candidate.metadata || {},
        };
        trace._search_text = `${trace.id} ${key} ${flattenTraceSearchText(trace)}`.toLowerCase();
        traces.push(trace);
      }
    }
  }

  let filtered = traces;
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
      light: "/assets/trackio_logo_type_light_transparent.png",
      dark: "/assets/trackio_logo_type_dark_transparent.png",
    },
    color_palette: settings.color_palette || [],
    plot_order: settings.plot_order || [],
    table_truncate_length: 250,
  };
}

export async function getProjectFiles() {
  if (fileListData) return fileListData;

  if (config.bucket_id) {
    const resp = await fetch(
      `https://huggingface.co/api/buckets/${config.bucket_id}/tree?prefix=media/files/&recursive=true`,
      { headers: authHeaders() },
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
    { headers: authHeaders() },
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

  const resp = await fetch(url, { headers: authHeaders() });
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
