const projectSelectEl = document.querySelector("#project-select");
const runListEl = document.querySelector("#run-list");
const metricsTitleEl = document.querySelector("#metrics-title");
const metricsSubtitleEl = document.querySelector("#metrics-subtitle");
const metricsGridEl = document.querySelector("#metrics-grid");
const tracesSubtitleEl = document.querySelector("#traces-subtitle");
const tracesBodyEl = document.querySelector("#traces-body");
const navButtons = Array.from(document.querySelectorAll(".nav-link"));
const pages = Array.from(document.querySelectorAll(".page"));

const state = {
  projects: [],
  selectedProject: null,
  runs: [],
  selectedRunIds: [],
};

const RUN_COLORS = [
  "#1f77b4",
  "#ff7f0e",
  "#2ca02c",
  "#d62728",
  "#9467bd",
  "#8c564b",
  "#e377c2",
  "#7f7f7f",
  "#bcbd22",
  "#17becf",
];

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

function runKey(run) {
  return run.id || run.name;
}

function colorForRun(run) {
  const index = state.runs.findIndex((candidate) => runKey(candidate) === runKey(run));
  return RUN_COLORS[((index >= 0 ? index : 0) % RUN_COLORS.length + RUN_COLORS.length) % RUN_COLORS.length];
}

function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return String(value);
  }
  if (Math.abs(value) >= 1000 || Math.abs(value) < 0.01) {
    return value.toExponential(2);
  }
  return value.toFixed(3);
}

function getQueryParams() {
  return new URLSearchParams(window.location.search);
}

function setQueryParams(params) {
  const next = new URL(window.location.href);
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) {
      next.searchParams.delete(key);
      continue;
    }
    next.searchParams.set(key, Array.isArray(value) ? value.join(",") : value);
  }
  window.history.replaceState({}, "", next);
}

function setActivePage(pageName) {
  navButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.pageTarget === pageName);
  });
  pages.forEach((page) => {
    page.classList.toggle("active", page.dataset.page === pageName);
  });
}

function bindNavigation() {
  navButtons.forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.pageTarget));
  });
}

function pickInitialProject(projects) {
  const params = getQueryParams();
  const project = params.get("project");
  if (project && projects.includes(project)) {
    return project;
  }
  return projects[0] || null;
}

function pickInitialRunIds(runs) {
  const params = getQueryParams();
  const fromUrl = (params.get("run_ids") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const validIds = runs.map(runKey);
  const selected = fromUrl.filter((id) => validIds.includes(id));
  if (selected.length) {
    return selected;
  }
  return runs.slice(0, 2).map(runKey);
}

function renderProjectSelect() {
  projectSelectEl.innerHTML = "";
  if (!state.projects.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No projects";
    projectSelectEl.appendChild(option);
    projectSelectEl.disabled = true;
    return;
  }

  projectSelectEl.disabled = false;
  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project;
    option.textContent = project;
    option.selected = project === state.selectedProject;
    projectSelectEl.appendChild(option);
  }
}

function renderRunList() {
  runListEl.innerHTML = "";
  if (!state.runs.length) {
    const empty = document.createElement("div");
    empty.className = "sidebar-empty";
    empty.textContent = "No runs yet";
    runListEl.appendChild(empty);
    return;
  }

  for (const run of state.runs) {
    const wrapper = document.createElement("label");
    wrapper.className = "run-option";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.selectedRunIds.includes(runKey(run));
    input.addEventListener("change", async () => {
      if (input.checked) {
        state.selectedRunIds = [...new Set([...state.selectedRunIds, runKey(run)])];
      } else {
        state.selectedRunIds = state.selectedRunIds.filter((id) => id !== runKey(run));
      }
      setQueryParams({
        project: state.selectedProject,
        run_ids: state.selectedRunIds,
      });
      await renderDashboard();
    });

    const marker = document.createElement("span");
    marker.className = "run-color-dot";
    marker.style.backgroundColor = colorForRun(run);

    const text = document.createElement("span");
    text.className = "run-option-text";
    text.innerHTML = `<strong>${run.name || "Unnamed run"}</strong>`;

    wrapper.appendChild(input);
    wrapper.appendChild(marker);
    wrapper.appendChild(text);
    runListEl.appendChild(wrapper);
  }
}

function chartPoints(rows, width, height, padding) {
  const values = rows.map((row) => row.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return rows.map((row, index) => {
    const x = padding + (index / Math.max(rows.length - 1, 1)) * (width - padding * 2);
    const y = height - padding - ((row.value - min) / span) * (height - padding * 2);
    return [x, y];
  });
}

function pathFromPoints(points) {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x} ${y}`).join(" ");
}

function renderMetricCard(metricName, rows, runName, color) {
  const card = document.createElement("article");
  card.className = "metric-card";
  if (!rows.length) {
    card.innerHTML = `
      <div class="metric-card-head">
        <div>
          <h3>${metricName}</h3>
          <div class="metric-run">${runName}</div>
        </div>
      </div>
      <div class="metric-empty">No numeric values logged for this metric.</div>
    `;
    return card;
  }

  const width = 640;
  const height = 220;
  const padding = 20;
  const points = chartPoints(rows, width, height, padding);
  const markers = points
    .map(([x, y]) => `<circle class="plot-marker" cx="${x}" cy="${y}" r="3.5"></circle>`)
    .join("");
  const latest = rows.at(-1);

  card.innerHTML = `
    <div class="metric-card-head">
      <div>
        <h3>${metricName}</h3>
        <div class="metric-run">${runName}</div>
      </div>
      <div class="metric-latest">${formatValue(latest.value)}</div>
    </div>
    <div class="plot-shell">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${metricName} line plot">
        <line class="plot-axis" x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}"></line>
        <path class="plot-line" d="${pathFromPoints(points)}" stroke="${color}"></path>
        ${markers}
      </svg>
    </div>
    <div class="metric-meta">Latest step ${latest.step ?? "?"} with ${rows.length} points</div>
  `;
  return card;
}

function textFromContent(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === "string") return part;
        if (typeof part?.text === "string") return part.text;
        if (typeof part?.content === "string") return part.content;
        return "";
      })
      .filter(Boolean)
      .join(" ");
  }
  if (typeof content?.text === "string") return content.text;
  return "";
}

function formatTraceTime(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return date.toLocaleString();
}

function renderTraceRows(traces) {
  tracesBodyEl.innerHTML = "";
  if (!traces.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5" class="empty-row">No traces for the selected runs.</td>';
    tracesBodyEl.appendChild(row);
    return;
  }

  for (const trace of traces) {
    const request = textFromContent(
      (trace.messages || []).find((message) => message?.role === "user")?.content,
    ) || "(no user message)";
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span class="trace-id">${trace.id}</span></td>
      <td class="trace-request">${request}</td>
      <td>${trace.run || "—"}</td>
      <td>${trace.step ?? "—"}</td>
      <td>${formatTraceTime(trace.timestamp)}</td>
    `;
    tracesBodyEl.appendChild(row);
  }
}

async function loadRuns() {
  if (!state.selectedProject) {
    state.runs = [];
    state.selectedRunIds = [];
    renderRunList();
    await renderDashboard();
    return;
  }

  state.runs = await api("get_runs_for_project", { project: state.selectedProject });
  state.selectedRunIds = pickInitialRunIds(state.runs);
  renderRunList();
  await renderDashboard();
}

async function renderDashboard() {
  metricsGridEl.innerHTML = "";
  tracesBodyEl.innerHTML = "";

  const selectedRuns = state.runs.filter((run) => state.selectedRunIds.includes(runKey(run)));
  metricsTitleEl.textContent = state.selectedProject || "Metrics";

  if (!state.selectedProject) {
    metricsSubtitleEl.textContent = "No Trackio projects found.";
    tracesSubtitleEl.textContent = "No traces available.";
    return;
  }

  if (!selectedRuns.length) {
    metricsSubtitleEl.textContent = "Select one or more runs in the sidebar.";
    tracesSubtitleEl.textContent = "Select one or more runs to load traces.";
    metricsGridEl.innerHTML = '<div class="empty-panel">No runs selected.</div>';
    renderTraceRows([]);
    return;
  }

  metricsSubtitleEl.textContent = `Plot cards for ${selectedRuns.length} selected run${selectedRuns.length === 1 ? "" : "s"}.`;
  tracesSubtitleEl.textContent = `Recent traces for ${selectedRuns.length} selected run${selectedRuns.length === 1 ? "" : "s"}.`;

  const traceGroups = [];

  for (const run of selectedRuns) {
    const metrics = await api("get_metrics_for_run", {
      project: state.selectedProject,
      run: run.name,
      run_id: run.id,
    });

    const metricSeries = await Promise.all(
      metrics.slice(0, 3).map(async (metricName) => ({
        metricName,
        rows: await api("get_metric_values", {
          project: state.selectedProject,
          run: run.name,
          run_id: run.id,
          metric_name: metricName,
        }),
      })),
    );

    metricSeries.forEach(({ metricName, rows }) => {
      const numericRows = rows.filter((row) => typeof row.value === "number" && Number.isFinite(row.value));
      metricsGridEl.appendChild(
        renderMetricCard(metricName, numericRows, run.name || "Unnamed run", colorForRun(run)),
      );
    });

    const runTraces = await api("get_traces", {
      project: state.selectedProject,
      run: run.name,
      run_id: run.id,
      sort: "request_time_desc",
      limit: 6,
    });
    traceGroups.push(...runTraces);
  }

  if (!metricsGridEl.children.length) {
    metricsGridEl.innerHTML = '<div class="empty-panel">No numeric metrics available.</div>';
  }

  traceGroups.sort((left, right) => String(right.timestamp || "").localeCompare(String(left.timestamp || "")));
  renderTraceRows(traceGroups.slice(0, 12));
}

async function load() {
  bindNavigation();
  projectSelectEl.addEventListener("change", async () => {
    state.selectedProject = projectSelectEl.value || null;
    setQueryParams({ project: state.selectedProject, run_ids: null });
    await loadRuns();
    renderProjectSelect();
  });
  try {
    state.projects = await api("get_all_projects");
    state.selectedProject = pickInitialProject(state.projects);
    renderProjectSelect();
    await loadRuns();
  } catch (error) {
    projectSelectEl.innerHTML = '<option value="">Error</option>';
    projectSelectEl.disabled = true;
    metricsSubtitleEl.textContent = "Could not load Trackio data.";
    metricsGridEl.innerHTML = '<div class="empty-panel">The starter could not reach the Trackio API.</div>';
    tracesSubtitleEl.textContent = "Could not load traces.";
    renderTraceRows([]);
  }
}

load();
