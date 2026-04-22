const projectTitle = document.querySelector("#project-title");
const projectsEl = document.querySelector("#projects");
const runsEl = document.querySelector("#runs");
const metricsEl = document.querySelector("#metrics");
const statusEl = document.querySelector("#status");
const metricHeaderEl = document.querySelector("#metric-header");

const state = {
  projects: [],
  selectedProject: null,
  runRecords: [],
  selectedRun: null,
};

async function api(name, payload = {}) {
  const response = await fetch(`/api/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const json = await response.json();
  if (!response.ok || json.error) {
    throw new Error(json.error || `Request failed for ${name}`);
  }
  return json.data;
}

function updateQueryParams(params) {
  const next = new URL(window.location.href);
  for (const [key, value] of Object.entries(params)) {
    if (value) {
      next.searchParams.set(key, value);
    } else {
      next.searchParams.delete(key);
    }
  }
  window.history.replaceState({}, "", next);
}

function getInitialProject(projects) {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("project");
  if (fromUrl && projects.includes(fromUrl)) {
    return fromUrl;
  }
  return projects[0] || null;
}

function getInitialRun(runRecords) {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("run");
  if (fromUrl) {
    const match = runRecords.find((record) => record.name === fromUrl);
    if (match) {
      return match;
    }
  }
  return runRecords[0] || null;
}

function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return String(value);
  }
  if (Math.abs(value) >= 1000 || Math.abs(value) < 0.01) {
    return value.toExponential(2);
  }
  return value.toFixed(4);
}

function metricStroke(index) {
  const palette = ["#d85f3d", "#2b6cb0", "#15803d", "#9a3412", "#7c3aed", "#0f766e"];
  return palette[index % palette.length];
}

function renderProjects(projects, selectedProject) {
  projectsEl.innerHTML = "";
  for (const project of projects) {
    const button = document.createElement("button");
    button.className = `chip${project === selectedProject ? " active" : ""}`;
    button.textContent = project;
    button.addEventListener("click", async () => {
      state.selectedProject = project;
      updateQueryParams({ project, run: null });
      await loadRuns(project);
      renderProjects(state.projects, state.selectedProject);
    });
    projectsEl.appendChild(button);
  }
}

function renderRuns(runRecords, selectedRun) {
  runsEl.innerHTML = "";
  if (!runRecords.length) {
    runsEl.innerHTML = '<div class="item"><strong>No runs yet</strong><div class="meta">Log a run and this panel will populate.</div></div>';
    return;
  }

  for (const record of runRecords.slice().reverse()) {
    const button = document.createElement("button");
    button.className = `run-card${selectedRun?.id === record.id ? " active" : ""}`;
    button.type = "button";
    button.addEventListener("click", async () => {
      state.selectedRun = record;
      updateQueryParams({ project: state.selectedProject, run: record.name || null });
      renderRuns(state.runRecords, state.selectedRun);
      await loadMetrics();
    });

    const title = document.createElement("strong");
    title.textContent = record.name || "Unnamed run";

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `Created: ${record.created_at || "unknown"}`;

    const idMeta = document.createElement("div");
    idMeta.className = "subtle";
    idMeta.textContent = `Run ID: ${record.id || "unknown"}`;

    button.appendChild(title);
    button.appendChild(meta);
    button.appendChild(idMeta);
    runsEl.appendChild(button);
  }
}

function buildPolyline(points, width, height, padding) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;

  return points
    .map((point, index) => {
      const x = padding + index * stepX;
      const y = height - padding - ((point.value - min) / range) * (height - padding * 2);
      return `${x},${y}`;
    })
    .join(" ");
}

function createMetricCard(metricName, series, index) {
  const item = document.createElement("article");
  item.className = "metric-card";

  const header = document.createElement("div");
  header.className = "metric-card-header";

  const title = document.createElement("strong");
  title.textContent = metricName;

  const latest = document.createElement("div");
  latest.className = "metric-value";
  latest.textContent = series.length ? formatValue(series.at(-1).value) : "No values";

  header.appendChild(title);
  header.appendChild(latest);

  if (!series.length) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = "No points logged for this metric yet.";
    item.appendChild(header);
    item.appendChild(meta);
    return item;
  }

  const chart = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  chart.setAttribute("viewBox", "0 0 320 120");
  chart.setAttribute("class", "metric-chart");

  const grid = document.createElementNS("http://www.w3.org/2000/svg", "path");
  grid.setAttribute("d", "M 12 108 H 308");
  grid.setAttribute("class", "metric-grid");

  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", buildPolyline(series, 320, 120, 12));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", metricStroke(index));
  line.setAttribute("stroke-width", "3");
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("stroke-linejoin", "round");

  chart.appendChild(grid);
  chart.appendChild(line);

  const meta = document.createElement("div");
  meta.className = "metric-meta";
  const latestPoint = series.at(-1);
  meta.textContent = `Latest step ${latestPoint.step ?? "?"} with ${series.length} points`;

  item.appendChild(header);
  item.appendChild(chart);
  item.appendChild(meta);
  return item;
}

function renderMetrics(metricSeries) {
  metricsEl.innerHTML = "";
  if (!metricSeries.length) {
    metricsEl.innerHTML = '<div class="item"><strong>No metrics yet</strong><div class="meta">This run has not logged any chartable metric values.</div></div>';
    return;
  }

  metricSeries.forEach(({ metricName, series }, index) => {
    metricsEl.appendChild(createMetricCard(metricName, series, index));
  });
}

async function loadRuns(project) {
  if (!project) {
    state.runRecords = [];
    state.selectedRun = null;
    renderRuns([], null);
    renderMetrics([]);
    metricHeaderEl.textContent = "Run Metrics";
    return;
  }

  statusEl.textContent = "Loading runs...";
  const runRecords = await api("get_runs_for_project", { project });
  state.runRecords = runRecords;
  state.selectedRun = getInitialRun(runRecords);
  renderRuns(state.runRecords, state.selectedRun);
  await loadMetrics();
}

async function loadMetrics() {
  const selectedRun = state.selectedRun;
  if (!state.selectedProject || !selectedRun) {
    metricHeaderEl.textContent = "Run Metrics";
    renderMetrics([]);
    statusEl.textContent = "Ready";
    return;
  }

  statusEl.textContent = "Loading metrics...";
  metricHeaderEl.textContent = `Metrics for ${selectedRun.name || "selected run"}`;

  const metricNames = await api("get_metrics_for_run", {
    project: state.selectedProject,
    run: selectedRun.name,
    run_id: selectedRun.id,
  });

  const metricSeries = await Promise.all(
    metricNames.slice(0, 6).map(async (metricName) => {
      const series = await api("get_metric_values", {
        project: state.selectedProject,
        run: selectedRun.name,
        run_id: selectedRun.id,
        metric_name: metricName,
      });
      return { metricName, series };
    })
  );

  renderMetrics(metricSeries);
  statusEl.textContent = "Ready";
}

async function load() {
  try {
    statusEl.textContent = "Loading projects...";
    state.projects = await api("get_all_projects");
    state.selectedProject = getInitialProject(state.projects);
    projectTitle.textContent = state.selectedProject || "No local Trackio projects";
    renderProjects(state.projects, state.selectedProject);

    if (!state.selectedProject) {
      renderRuns([], null);
      renderMetrics([]);
      metricHeaderEl.textContent = "Run Metrics";
      statusEl.textContent = "Ready";
      return;
    }

    updateQueryParams({ project: state.selectedProject });
    await loadRuns(state.selectedProject);
    projectTitle.textContent = state.selectedProject;
  } catch (error) {
    projectTitle.textContent = "Frontend error";
    runsEl.innerHTML = "";
    const item = document.createElement("div");
    item.className = "item";
    const title = document.createElement("strong");
    title.textContent = "Could not load Trackio data";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = error.message;
    item.appendChild(title);
    item.appendChild(meta);
    runsEl.appendChild(item);
    metricsEl.innerHTML = "";
    statusEl.textContent = "Error";
  }
}

load();
