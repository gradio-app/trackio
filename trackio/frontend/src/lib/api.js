import * as staticApi from "./staticApi.js";

const BASE = window.__trackio_base || "";

let _staticMode = null;
let _staticModePromise = null;

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
  const url = `${BASE}/gradio_api/call${apiName}`;
  const resp = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...getOauthSessionHeader() },
    body: JSON.stringify({ data: Object.values(params) }),
  });
  if (!resp.ok) {
    throw new Error(`API call ${apiName} failed: ${resp.status}`);
  }
  const json = await resp.json();
  const eventId = json.event_id;

  const dataResp = await fetch(`${BASE}/gradio_api/call${apiName}/${eventId}`, {
    credentials: "include",
  });
  if (!dataResp.ok) {
    throw new Error(`API result ${apiName} failed: ${dataResp.status}`);
  }

  const text = await dataResp.text();
  const lines = text.trim().split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith("event: complete")) {
      const dataLine = lines[i + 1];
      if (dataLine && dataLine.startsWith("data: ")) {
        const raw = dataLine.slice(6);
        const sanitized = raw
          .replace(/:\s*Infinity\b/g, ": null")
          .replace(/:\s*-Infinity\b/g, ": null")
          .replace(/:\s*NaN\b/g, ": null");
        const parsed = JSON.parse(sanitized);
        return Array.isArray(parsed) ? parsed[0] : parsed;
      }
    }
    if (lines[i].startsWith("event: error")) {
      const dataLine = lines[i + 1];
      if (dataLine && dataLine.startsWith("data: ")) {
        throw new Error(JSON.parse(dataLine.slice(6)));
      }
    }
  }
  throw new Error(`No complete event for ${apiName}`);
}

export async function getAllProjects() {
  if (await isStaticMode()) return staticApi.getAllProjects();
  return await callApi("/get_all_projects");
}

export async function getRunsForProject(project) {
  if (await isStaticMode()) return staticApi.getRunsForProject(project);
  return await callApi("/get_runs_for_project", { project });
}

export async function getMetricsForRun(project, run) {
  if (await isStaticMode()) return staticApi.getMetricsForRun(project, run);
  return await callApi("/get_metrics_for_run", { project, run });
}

export async function getLogs(project, run) {
  if (await isStaticMode()) return staticApi.getLogs(project, run);
  return await callApi("/get_logs", { project, run });
}

export async function getProjectSummary(project) {
  if (await isStaticMode()) return staticApi.getProjectSummary(project);
  return await callApi("/get_project_summary", { project });
}

export async function getRunSummary(project, run) {
  if (await isStaticMode()) return staticApi.getRunSummary(project, run);
  return await callApi("/get_run_summary", { project, run });
}

export async function getAlerts(project, run, level, since) {
  if (await isStaticMode()) return staticApi.getAlerts(project, run, level, since);
  return await callApi("/get_alerts", { project, run, level, since });
}

export async function getSystemMetricsForRun(project, run) {
  if (await isStaticMode()) return staticApi.getSystemMetricsForRun(project, run);
  return await callApi("/get_system_metrics_for_run", { project, run });
}

export async function getSystemLogs(project, run) {
  if (await isStaticMode()) return staticApi.getSystemLogs(project, run);
  return await callApi("/get_system_logs", { project, run });
}

export async function getSnapshot(project, run, step) {
  if (await isStaticMode()) return staticApi.getSnapshot(project, run, step);
  return await callApi("/get_snapshot", {
    project,
    run,
    step,
    around_step: null,
    at_time: null,
    window: null,
  });
}

export async function getMetricValues(project, run, metricName) {
  if (await isStaticMode())
    return staticApi.getMetricValues(project, run, metricName);
  return await callApi("/get_metric_values", {
    project,
    run,
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
  if (await isStaticMode()) return staticApi.deleteRun(project, run);
  return await callApi("/delete_run", { project, run });
}

export async function renameRun(project, oldName, newName) {
  if (await isStaticMode()) return staticApi.renameRun(project, oldName, newName);
  return await callApi("/rename_run", {
    project,
    old_name: oldName,
    new_name: newName,
  });
}

export function getAssetUrl(path) {
  if (_staticMode) return staticApi.getAssetUrl(path);
  return `${BASE}/gradio_api/file=${path}`;
}

export function getMediaUrl(path) {
  if (_staticMode) return staticApi.getMediaUrl(path);
  return `${BASE}/gradio_api/file=${path}`;
}
