const BASE = window.__trackio_base || "";

export async function callApi(apiName, params = {}) {
  const url = `${BASE}/gradio_api/call${apiName}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: Object.values(params) }),
  });
  if (!resp.ok) {
    throw new Error(`API call ${apiName} failed: ${resp.status}`);
  }
  const json = await resp.json();
  const eventId = json.event_id;

  const dataResp = await fetch(
    `${BASE}/gradio_api/call${apiName}/${eventId}`,
  );
  if (!dataResp.ok) {
    throw new Error(`API result ${apiName} failed: ${dataResp.status}`);
  }

  const text = await dataResp.text();
  const lines = text.trim().split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].startsWith("event: complete")) {
      const dataLine = lines[i + 1];
      if (dataLine && dataLine.startsWith("data: ")) {
        const parsed = JSON.parse(dataLine.slice(6));
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
  const data = await callApi("/get_all_projects");
  return data;
}

export async function getRunsForProject(project) {
  const data = await callApi("/get_runs_for_project", { project });
  return data;
}

export async function getMetricsForRun(project, run) {
  const data = await callApi("/get_metrics_for_run", { project, run });
  return data;
}

export async function getLogs(project, run) {
  const data = await callApi("/get_logs", { project, run });
  return data;
}

export async function getProjectSummary(project) {
  const data = await callApi("/get_project_summary", { project });
  return data;
}

export async function getRunSummary(project, run) {
  const data = await callApi("/get_run_summary", { project, run });
  return data;
}

export async function getAlerts(project, run, level, since) {
  const data = await callApi("/get_alerts", { project, run, level, since });
  return data;
}

export async function getSystemMetricsForRun(project, run) {
  const data = await callApi("/get_system_metrics_for_run", { project, run });
  return data;
}

export async function getSystemLogs(project, run) {
  const data = await callApi("/get_system_logs", { project, run });
  return data;
}

export async function getSnapshot(project, run, step) {
  const data = await callApi("/get_snapshot", {
    project,
    run,
    step,
    around_step: null,
    at_time: null,
    window: null,
  });
  return data;
}

export async function getMetricValues(project, run, metricName) {
  const data = await callApi("/get_metric_values", {
    project,
    run,
    metric_name: metricName,
    step: null,
    around_step: null,
    at_time: null,
    window: null,
  });
  return data;
}

export function getAssetUrl(path) {
  return `${BASE}/gradio_api/file=${path}`;
}

export function getMediaUrl(path) {
  return `${BASE}/gradio_api/file=${path}`;
}
