import * as staticApi from "./staticApi.js";
import { registerRateLimitHit } from "./hostPolling.js";

const BASE = window.__trackio_base || "";

let _staticMode = null;
let _staticModePromise = null;
let _mediaDir = "";

async function _detectStaticMode() {
  try {
    const resp = await fetch(`${BASE}/config.json`);
    if (resp.ok) {
      const cfg = await resp.json();
      if (cfg.mode === "static") {
        await staticApi.initialize(cfg);
        return true;
      }
    }
  } catch {
    // not static mode
  }
  return false;
}

export async function isStaticMode() {
  if (_staticMode !== null) return _staticMode;
  if (!_staticModePromise) {
    _staticModePromise = _detectStaticMode().then((result) => {
      _staticMode = result;
      return result;
    });
  }
  return _staticModePromise;
}

function getOauthSessionHeader() {
  const sid = sessionStorage.getItem("trackio_oauth_session");
  return sid ? { "x-trackio-oauth-session": sid } : {};
}

export async function callApi(apiName, params = {}) {
  const cleanApiName = apiName.startsWith("/") ? apiName.slice(1) : apiName;
  const url = `${BASE}/api/${cleanApiName}`;
  const resp = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...getOauthSessionHeader() },
    body: JSON.stringify(params),
  });
  if (resp.status === 429) {
    registerRateLimitHit();
  }
  if (!resp.ok) {
    throw new Error(`API call ${apiName} failed: ${resp.status}`);
  }
  const json = await resp.json();
  if (json.error) {
    throw new Error(json.error);
  }
  return json.data;
}

export async function getAllProjects() {
  if (await isStaticMode()) return staticApi.getAllProjects();
  return await callApi("/get_all_projects");
}

export async function getRunsForProject(project) {
  if (await isStaticMode()) return staticApi.getRunsForProject(project);
  return await callApi("/get_runs_for_project", { project });
}

function normalizeRun(run) {
  if (run == null) return { run: null, run_id: null };
  if (typeof run === "string") return { run, run_id: null };
  return { run: run.name ?? null, run_id: run.id ?? null };
}

export async function getMetricsForRun(project, run) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.getMetricsForRun(project, run);
  return await callApi("/get_metrics_for_run", params);
}

export async function getLogs(project, run) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.getLogs(project, run);
  return await callApi("/get_logs", params);
}

export async function getLogsBatch(project, runs) {
  if (await isStaticMode()) {
    const out = [];
    for (const run of runs) {
      const logs = await staticApi.getLogs(project, run);
      out.push({ ...normalizeRun(run), logs });
    }
    return out;
  }
  const payload = {
    project,
    runs: runs.map((run) => normalizeRun(run)),
  };
  return await callApi("/get_logs_batch", payload);
}

function sqlString(value) {
  return `'${String(value ?? "").replaceAll("'", "''")}'`;
}

const DEFAULT_METRIC_MAX_POINTS = 1500;

function scalarLogsFromQueryRows(rows) {
  return (rows || []).map((row) => {
    const metrics = (() => {
      try {
        return JSON.parse(row.metrics || "{}");
      } catch {
        return {};
      }
    })();
    return {
      ...metrics,
      timestamp: row.timestamp,
      step: row.step,
    };
  });
}

function scalarOnlyLogs(logs) {
  return (logs || []).map((row) => {
    const out = {
      timestamp: row.timestamp,
      step: row.step,
    };
    for (const [key, value] of Object.entries(row)) {
      if (key === "timestamp" || key === "step") continue;
      if (typeof value === "number" && Number.isFinite(value)) out[key] = value;
    }
    return out;
  });
}

async function queryProject(project, query) {
  return await callApi("/query_project", { project, query });
}

export async function getTraceStepCounts(project, run) {
  if (await isStaticMode()) return [];

  const normalized = normalizeRun(run);
  const where = normalized.run_id
    ? `m.run_id = ${sqlString(normalized.run_id)}`
    : `m.run_name = ${sqlString(normalized.run)}`;
  const result = await queryProject(
    project,
    `
      WITH trace_metrics AS (
        SELECT
          m.step AS step,
          j.type AS value_type,
          j.value AS value
        FROM metrics m, json_each(CAST(m.metrics AS TEXT)) j
        WHERE ${where}
          AND m.step IS NOT NULL
          AND j.type IN ('array', 'object')
      )
      SELECT
        step,
        SUM(
          CASE
            WHEN value_type = 'array' THEN json_array_length(value)
            ELSE 1
          END
        ) AS trace_count
      FROM trace_metrics
      WHERE (
        value_type = 'array'
        AND (
          json_extract(value, '$[0]._type') = 'trackio.trace'
          OR json_extract(value, '$[0].messages') IS NOT NULL
        )
      )
      OR (
        value_type = 'object'
        AND (
          json_extract(value, '$._type') = 'trackio.trace'
          OR json_extract(value, '$.messages') IS NOT NULL
        )
      )
      GROUP BY step
      ORDER BY step
    `,
  );
  return (result.rows || []).map((row) => ({
    step: Number(row.step),
    count: Number(row.trace_count || 0),
  })).filter((row) => Number.isFinite(row.step) && row.count > 0);
}

export async function getScalarLogsBatch(project, runs) {
  if (await isStaticMode()) {
    const out = [];
    for (const run of runs) {
      const logs = await staticApi.getLogs(project, run);
      out.push({ ...normalizeRun(run), logs: scalarOnlyLogs(logs) });
    }
    return out;
  }

  const out = [];
  for (const run of runs) {
    const normalized = normalizeRun(run);
    const where = normalized.run_id
      ? `m.run_id = ${sqlString(normalized.run_id)}`
      : `m.run_name = ${sqlString(normalized.run)}`;
    const result = await queryProject(
      project,
      `
        WITH scalar_rows AS (
          SELECT
            m.timestamp,
            m.step,
            json_group_object(j.key, j.value) AS metrics
          FROM metrics m, json_each(CAST(m.metrics AS TEXT)) j
          WHERE ${where}
            AND j.type IN ('integer', 'real')
          GROUP BY m.id, m.timestamp, m.step
        ),
        numbered AS (
          SELECT
            timestamp,
            step,
            metrics,
            ROW_NUMBER() OVER (ORDER BY timestamp) - 1 AS row_index,
            COUNT(*) OVER () AS row_count
          FROM scalar_rows
        )
        SELECT timestamp, step, metrics
        FROM numbered
        WHERE row_count <= ${DEFAULT_METRIC_MAX_POINTS}
          OR row_index = 0
          OR row_index = row_count - 1
          OR CAST(row_index * ${DEFAULT_METRIC_MAX_POINTS} / row_count AS INTEGER)
            != CAST((row_index - 1) * ${DEFAULT_METRIC_MAX_POINTS} / row_count AS INTEGER)
        ORDER BY timestamp
      `,
    );
    out.push({
      ...normalized,
      logs: scalarLogsFromQueryRows(result.rows),
    });
  }
  return out;
}

export async function getTraces(project, run, options = {}) {
  const params = { project, ...normalizeRun(run), ...options };
  if (await isStaticMode()) return staticApi.getTraces(project, run, options);
  return await callApi("/get_traces", params);
}

export async function getProjectSummary(project) {
  if (await isStaticMode()) return staticApi.getProjectSummary(project);
  return await callApi("/get_project_summary", { project });
}

export async function getRunSummary(project, run) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.getRunSummary(project, run);
  return await callApi("/get_run_summary", params);
}

export async function getAlerts(project, run, level, since) {
  const params = { project, ...normalizeRun(run), level, since };
  if (await isStaticMode()) return staticApi.getAlerts(project, run, level, since);
  return await callApi("/get_alerts", params);
}

export async function getSystemMetricsForRun(project, run) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.getSystemMetricsForRun(project, run);
  return await callApi("/get_system_metrics_for_run", params);
}

export async function getSystemLogs(project, run) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.getSystemLogs(project, run);
  return await callApi("/get_system_logs", params);
}

export async function getSystemLogsBatch(project, runs) {
  if (await isStaticMode()) {
    const out = [];
    for (const run of runs) {
      const logs = await staticApi.getSystemLogs(project, run);
      out.push({ ...normalizeRun(run), logs });
    }
    return out;
  }
  return await callApi("/get_system_logs_batch", {
    project,
    runs: runs.map((run) => normalizeRun(run)),
  });
}

export async function getSnapshot(project, run, step) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.getSnapshot(project, run, step);
  return await callApi("/get_snapshot", {
    ...params,
    step,
    around_step: null,
    at_time: null,
    window: null,
  });
}

export async function getMetricValues(project, run, metricName) {
  if (await isStaticMode())
    return staticApi.getMetricValues(project, run, metricName);
  const params = { project, ...normalizeRun(run) };
  return await callApi("/get_metric_values", {
    ...params,
    metric_name: metricName,
    step: null,
    around_step: null,
    at_time: null,
    window: null,
  });
}

export async function getSettings() {
  if (await isStaticMode()) return staticApi.getSettings();
  return await callApi("/get_settings");
}

export async function getProjectFiles(project) {
  if (await isStaticMode()) return staticApi.getProjectFiles(project);
  return await callApi("/get_project_files", { project });
}

export async function getRunMutationStatus() {
  if (await isStaticMode()) return staticApi.getRunMutationStatus();
  return await callApi("/get_run_mutation_status", {});
}

export async function deleteRun(project, run) {
  const params = { project, ...normalizeRun(run) };
  if (await isStaticMode()) return staticApi.deleteRun(project, run);
  return await callApi("/delete_run", params);
}

export async function renameRun(project, oldRun, newName) {
  const run = normalizeRun(oldRun);
  if (await isStaticMode()) return staticApi.renameRun(project, oldRun, newName);
  return await callApi("/rename_run", {
    project,
    old_name: run.run,
    run_id: run.run_id,
    new_name: newName,
  });
}

export function setMediaDir(dir) {
  _mediaDir = dir ? dir + "/" : "";
}

export function getAssetUrl(path) {
  if (_staticMode) return staticApi.getAssetUrl(path);
  return `${BASE}/file?path=${encodeURIComponent(`${_mediaDir}${path}`)}`;
}

export function getMediaUrl(path) {
  if (_staticMode) return staticApi.getMediaUrl(path);
  return `${BASE}/file?path=${encodeURIComponent(`${_mediaDir}${path}`)}`;
}

export function getFileUrl(path) {
  if (_staticMode) return staticApi.getMediaUrl(path);
  return `${BASE}/file?path=${encodeURIComponent(path)}`;
}

export async function getReadOnlySource() {
  if (await isStaticMode()) return staticApi.getReadOnlySource();
  return null;
}

export async function fetchMediaBlob(path) {
  if (_staticMode) return staticApi.fetchMediaBlob(path);
  return getMediaUrl(path);
}
