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

/*
Trackio routes used by this starter today:
- /api/get_all_projects
- /api/get_runs_for_project
- /api/get_metrics_for_run
- /api/get_metric_values
- /api/get_traces

Useful routes for expanding this starter toward the full dashboard:
- /api/get_system_metrics_for_run
- /api/get_system_logs
- /api/get_system_logs_batch
- /api/get_logs
- /api/get_logs_batch
- /api/get_snapshot
- /api/get_alerts
- /api/query_project
- /api/get_project_summary
- /api/get_run_summary
- /api/get_project_files
- /api/get_settings
- /api/get_run_mutation_status
- /api/delete_run
- /api/rename_run
- /api/force_sync
- /api/bulk_upload_media
- /api/upload

File/media URLs:
- /file?path=ABSOLUTE_PATH_FROM_API
*/

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

function chartPoints(rows, width, height, padding, min, max) {
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

function renderMetricCard(metricName, seriesByRun) {
  const card = document.createElement("article");
  card.className = "metric-card";
  const nonEmptySeries = seriesByRun.filter((entry) => entry.rows.length);
  if (!nonEmptySeries.length) {
    card.innerHTML = `
      <div class="metric-card-head">
        <div>
          <h3>${metricName}</h3>
          <div class="metric-run">Selected runs</div>
        </div>
      </div>
      <div class="metric-empty">No numeric values logged for this metric.</div>
    `;
    return card;
  }

  const width = 640;
  const height = 220;
  const padding = 20;
  const values = nonEmptySeries.flatMap((entry) => entry.rows.map((row) => row.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const lineMarkup = nonEmptySeries
    .map((entry) => {
      const points = chartPoints(entry.rows, width, height, padding, min, max);
      const markers = points
        .map(([x, y]) => `<circle class="plot-marker" cx="${x}" cy="${y}" r="3.5" style="stroke:${entry.color}"></circle>`)
        .join("");
      return `
        <path class="plot-line" d="${pathFromPoints(points)}" stroke="${entry.color}"></path>
        ${markers}
      `;
    })
    .join("");
  const legendMarkup = nonEmptySeries
    .map(
      (entry) => `
        <span class="metric-legend-item">
          <span class="metric-legend-dot" style="background:${entry.color}"></span>
          ${entry.runName}
        </span>
      `,
    )
    .join("");
  const latestSummary = nonEmptySeries
    .map((entry) => `${entry.runName}: ${formatValue(entry.rows.at(-1).value)}`)
    .join(" | ");

  card.innerHTML = `
    <div class="metric-card-head">
      <div>
        <h3>${metricName}</h3>
        <div class="metric-run">${nonEmptySeries.length} run${nonEmptySeries.length === 1 ? "" : "s"} overlaid</div>
      </div>
      <div class="metric-latest">${latestSummary}</div>
    </div>
    <div class="plot-shell">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${metricName} line plot">
        <line class="plot-axis" x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}"></line>
        ${lineMarkup}
      </svg>
    </div>
    <div class="metric-legend">${legendMarkup}</div>
    <div class="metric-meta">Comparing ${nonEmptySeries.length} selected runs on the same metric scale.</div>
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderMessageContent(content) {
  if (typeof content === "string") {
    return `<div class="trace-message-text">${escapeHtml(content)}</div>`;
  }
  if (Array.isArray(content)) {
    const items = content
      .map((part) => {
        if (typeof part === "string") {
          return `<div class="trace-message-text">${escapeHtml(part)}</div>`;
        }
        if (typeof part?.text === "string") {
          return `<div class="trace-message-text">${escapeHtml(part.text)}</div>`;
        }
        if (typeof part?.content === "string") {
          return `<div class="trace-message-text">${escapeHtml(part.content)}</div>`;
        }
        return `<div class="trace-message-text trace-message-muted">[non-text content]</div>`;
      })
      .join("");
    return items || '<div class="trace-message-text trace-message-muted">(empty)</div>';
  }
  if (typeof content?.text === "string") {
    return `<div class="trace-message-text">${escapeHtml(content.text)}</div>`;
  }
  return '<div class="trace-message-text trace-message-muted">(empty)</div>';
}

function renderTraceDetail(trace) {
  const messages = Array.isArray(trace.messages) ? trace.messages : [];
  if (!messages.length) {
    return '<div class="trace-message-text trace-message-muted">No trace messages.</div>';
  }
  return messages
    .map((message) => {
      const role = escapeHtml(message?.role || "unknown");
      return `
        <div class="trace-message">
          <div class="trace-message-role">${role}</div>
          ${renderMessageContent(message?.content)}
        </div>
      `;
    })
    .join("");
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
    row.className = "trace-summary-row";
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-expanded", "false");
    row.innerHTML = `
      <td><span class="trace-id">${trace.id}</span></td>
      <td class="trace-request">${request}</td>
      <td>${trace.run || "—"}</td>
      <td>${trace.step ?? "—"}</td>
      <td>${formatTraceTime(trace.timestamp)}</td>
    `;
    const detailRow = document.createElement("tr");
    detailRow.className = "trace-detail-row";
    detailRow.hidden = true;
    detailRow.innerHTML = `
      <td colspan="5">
        <div class="trace-detail-shell">
          <div class="trace-detail-head">
            <div>
              <strong>${escapeHtml(trace.id)}</strong>
              <div class="trace-detail-meta">${escapeHtml(trace.run || "—")} | step ${escapeHtml(trace.step ?? "—")} | ${escapeHtml(formatTraceTime(trace.timestamp))}</div>
            </div>
          </div>
          <div class="trace-message-list">
            ${renderTraceDetail(trace)}
          </div>
        </div>
      </td>
    `;
    const toggleRow = () => {
      const expanded = row.getAttribute("aria-expanded") === "true";
      row.setAttribute("aria-expanded", expanded ? "false" : "true");
      row.classList.toggle("expanded", !expanded);
      detailRow.hidden = expanded;
    };
    row.addEventListener("click", toggleRow);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleRow();
      }
    });
    tracesBodyEl.appendChild(row);
    tracesBodyEl.appendChild(detailRow);
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
  const metricMap = new Map();

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
      if (!metricMap.has(metricName)) {
        metricMap.set(metricName, []);
      }
      metricMap.get(metricName).push({
        runName: run.name || "Unnamed run",
        color: colorForRun(run),
        rows: numericRows,
      });
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

  for (const [metricName, seriesByRun] of metricMap.entries()) {
    metricsGridEl.appendChild(renderMetricCard(metricName, seriesByRun));
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
