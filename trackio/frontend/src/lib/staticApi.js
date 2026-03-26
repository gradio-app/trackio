import { readParquet } from "./parquetReader.js";

let config = null;
let metricsData = null;
let systemData = null;
let configsData = null;
let runsData = null;
let settingsData = null;

function datasetUrl(filename) {
  return `https://huggingface.co/datasets/${config.dataset_id}/resolve/main/${filename}`;
}

function authHeaders() {
  if (config.hf_token) {
    return { Authorization: `Bearer ${config.hf_token}` };
  }
  return {};
}

export async function initialize(cfg) {
  config = cfg;
}

export function getReadOnlySource() {
  if (!config || config.mode !== "static" || !config.dataset_id) return null;
  return {
    url: `https://huggingface.co/datasets/${config.dataset_id}`,
  };
}

async function getMetricsData() {
  if (metricsData) return metricsData;
  metricsData = await readParquet(datasetUrl("metrics.parquet"), authHeaders());
  return metricsData;
}

async function getSystemData() {
  if (systemData) return systemData;
  systemData = await readParquet(
    datasetUrl("system_metrics.parquet"),
    authHeaders(),
  );
  return systemData;
}

async function getConfigsData() {
  if (configsData) return configsData;
  configsData = await readParquet(datasetUrl("configs.parquet"), authHeaders());
  return configsData;
}

async function getRunsJson() {
  if (runsData) return runsData;
  const resp = await fetch(datasetUrl("runs.json"), { headers: authHeaders() });
  if (!resp.ok) {
    runsData = [];
    return runsData;
  }
  runsData = await resp.json();
  return runsData;
}

async function getSettingsJson() {
  if (settingsData) return settingsData;
  const resp = await fetch(datasetUrl("settings.json"), { headers: authHeaders() });
  if (!resp.ok) {
    settingsData = {};
    return settingsData;
  }
  settingsData = await resp.json();
  return settingsData;
}

const STRUCTURAL_KEYS = new Set([
  "id",
  "run_name",
  "timestamp",
  "step",
  "log_id",
  "space_id",
  "created_at",
]);

function rowToObj(row, columns) {
  const obj = {};
  for (let i = 0; i < columns.length; i++) {
    obj[columns[i]] = row[i];
  }
  return obj;
}

function parseRows(raw) {
  if (!raw || raw.length === 0) return { rows: [], columns: [] };
  const columns = Object.keys(raw[0]);
  const rows = raw.map((r) => {
    const obj = {};
    for (const col of columns) {
      obj[col] = r[col];
    }
    return obj;
  });
  return { rows, columns };
}

export async function getAllProjects() {
  return [config.project];
}

export async function getRunsForProject() {
  const runs = await getRunsJson();
  return runs.map((r) => r.name);
}

export async function getMetricsForRun(_project, run) {
  const raw = await getMetricsData();
  const { rows, columns } = parseRows(raw);
  const metricCols = columns.filter((c) => !STRUCTURAL_KEYS.has(c));

  const runRows = rows.filter((r) => r.run_name === run);
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
  const runRows = rows.filter((r) => r.run_name === run);

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

export async function getProjectSummary() {
  const runs = await getRunsJson();
  const runNames = runs.map((r) => r.name);
  const lastSteps = runs.map((r) => r.last_step || 0);
  return {
    project: config.project,
    num_runs: runs.length,
    runs: runNames,
    last_activity: lastSteps.length ? Math.max(...lastSteps) : null,
  };
}

export async function getRunSummary(_project, run) {
  const runs = await getRunsJson();
  const runMeta = runs.find((r) => r.name === run);
  if (!runMeta) {
    return {
      project: config.project,
      run,
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
  const cfgRow = cfgRows.find((r) => r.run_name === run);
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
    run,
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

  const runRows = rows.filter((r) => r.run_name === run);
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
  const runRows = rows.filter((r) => r.run_name === run);

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
  let runRows = rows.filter((r) => r.run_name === run);

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
  const runRows = rows.filter((r) => r.run_name === run);

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
  return [];
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

export function getAssetUrl(path) {
  return datasetUrl(`media/${path}`);
}

export function getMediaUrl(path) {
  return datasetUrl(`media/${path}`);
}
