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

function updateProjectParam(project) {
  const params = new URLSearchParams(window.location.search);
  params.set("project", project);
  window.location.search = params.toString();
}

function renderList(element, values, emptyLabel) {
  element.innerHTML = "";
  if (!values.length) {
    const item = document.createElement("div");
    item.className = "item";
    item.textContent = emptyLabel;
    element.appendChild(item);
    return;
  }
  for (const value of values) {
    const item = document.createElement("div");
    item.className = "item";
    item.textContent = value;
    element.appendChild(item);
  }
}

function renderOptions(selectEl, options, selectedValue, labelForOption) {
  selectEl.innerHTML = "";
  for (const option of options) {
    const el = document.createElement("option");
    el.value = option.value;
    el.textContent = labelForOption(option);
    if (option.value === selectedValue) {
      el.selected = true;
    }
    selectEl.appendChild(el);
  }
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function getChartableRows(rows) {
  return rows.filter((row) => isFiniteNumber(row.value));
}

function isChartableSeries(rows) {
  return getChartableRows(rows).length >= 2;
}

function formatValue(value) {
  if (!isFiniteNumber(value)) return String(value);
  if (Math.abs(value) >= 1000 || Math.abs(value) < 0.01) return value.toExponential(2);
  return value.toFixed(3);
}

function buildPath(points) {
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x} ${y}`).join(" ");
}

function buildAreaPath(points, height) {
  if (!points.length) return "";
  const line = buildPath(points);
  const [lastX] = points[points.length - 1];
  const [firstX] = points[0];
  return `${line} L ${lastX} ${height} L ${firstX} ${height} Z`;
}

function renderMetricCard(metric, rows) {
  const chartableRows = getChartableRows(rows);
  const width = 560;
  const height = 190;
  const padding = 18;
  const values = chartableRows.map((row) => row.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = chartableRows.map((row, index) => {
    const x = padding + (index / Math.max(chartableRows.length - 1, 1)) * (width - padding * 2);
    const y = height - padding - ((row.value - min) / span) * (height - padding * 2);
    return [x, y];
  });
  const latest = chartableRows[chartableRows.length - 1];
  const first = chartableRows[0];
  const skippedPoints = rows.length - chartableRows.length;
  const markers = points
    .map(
      ([x, y], index) =>
        `<circle class="chart-marker" cx="${x}" cy="${y}" r="${index === points.length - 1 ? 5 : 3.6}"></circle>`,
    )
    .join("");
  const card = document.createElement("article");
  card.className = "metric-card";
  card.innerHTML = `
    <h3>${metric}</h3>
    <div class="metric-meta">Latest ${formatValue(latest.value)} | ${chartableRows.length} plotted${skippedPoints ? ` | ${skippedPoints} skipped` : ""}</div>
    <div class="chart-frame">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${metric} line chart">
        <line class="chart-axis" x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}"></line>
        <line class="chart-axis faint" x1="${padding}" y1="${padding}" x2="${width - padding}" y2="${padding}"></line>
        <path class="chart-fill" d="${buildAreaPath(points, height - padding)}"></path>
        <path class="chart-line" d="${buildPath(points)}"></path>
        ${markers}
      </svg>
    </div>
    <div class="metric-value">${formatValue(first.value)} -> ${formatValue(latest.value)}</div>
  `;
  return card;
}

async function renderMetrics(element, project, run) {
  element.innerHTML = "";
  const metrics = await api("get_metrics_for_run", { project, run: run.name, run_id: run.id });
  if (!metrics.length) {
    renderList(element, [], "No metrics yet");
    return 0;
  }

  const rowsByMetric = await Promise.all(
    metrics.slice(0, 12).map(async (metric) => ({
      metric,
      rows: await api("get_metric_values", {
        project,
        run: run.name,
        run_id: run.id,
        metric_name: metric,
      }),
    })),
  );

  const chartable = rowsByMetric.filter((entry) => isChartableSeries(entry.rows));
  const other = rowsByMetric.filter((entry) => !isChartableSeries(entry.rows)).map((entry) => entry.metric);

  if (chartable.length) {
    const grid = document.createElement("div");
    grid.className = "metric-grid";
    for (const entry of chartable.slice(0, 6)) grid.appendChild(renderMetricCard(entry.metric, entry.rows));
    element.appendChild(grid);
  } else {
    renderList(element, [], "No numeric metrics available for charting");
  }

  if (other.length) {
    const extras = document.createElement("section");
    extras.className = "metric-extras";
    extras.innerHTML = "<h3>Other Logged Items</h3>";
    for (const metric of other) {
      const pill = document.createElement("span");
      pill.className = "metric-pill";
      pill.textContent = metric;
      extras.appendChild(pill);
    }
    element.appendChild(extras);
  }

  return metrics.length;
}

export async function mountTheme({
  title,
  projectSelect,
  runSelect,
  metricsEl,
  metricsSubtitle,
  projectSummary,
  runsCount,
  metricsCount,
  selectedRunName,
}) {
  try {
    const projects = await api("get_all_projects");
    const params = new URLSearchParams(window.location.search);
    const selectedProject =
      params.get("project") && projects.includes(params.get("project")) ? params.get("project") : projects[0];

    title.textContent = selectedProject || "No project";
    projectSummary.textContent = selectedProject ? "Wide charts, visible markers, and deliberate spacing." : "Choose a project and run.";
    renderOptions(projectSelect, projects.map((project) => ({ value: project })), selectedProject, (option) => option.value);
    projectSelect.onchange = () => updateProjectParam(projectSelect.value);

    if (!selectedProject) {
      renderList(metricsEl, [], "No metrics yet");
      selectedRunName.textContent = "No run";
      return;
    }

    const runs = await api("get_runs_for_project", { project: selectedProject });
    runsCount.textContent = String(runs.length);
    if (!runs.length) {
      runSelect.innerHTML = "";
      metricsCount.textContent = "0";
      selectedRunName.textContent = "No run";
      renderList(metricsEl, [], "No metrics yet");
      return;
    }

    const paramsRunId = params.get("run_id");
    let selectedRun = runs.find((run) => run.id === paramsRunId) || runs[0];
    renderOptions(runSelect, runs.map((run) => ({ value: run.id, name: run.name || "Unnamed run" })), selectedRun.id, (option) => option.name);

    const updateSelectedRun = async (runId) => {
      selectedRun = runs.find((run) => run.id === runId) || runs[0];
      runSelect.value = selectedRun.id;
      selectedRunName.textContent = selectedRun.name || "Unnamed run";
      metricsSubtitle.textContent = `Metric cards for ${selectedRun.name || "the selected run"}.`;
      metricsCount.textContent = String(await renderMetrics(metricsEl, selectedProject, selectedRun));
    };

    runSelect.onchange = () => updateSelectedRun(runSelect.value);
    await updateSelectedRun(selectedRun.id);
  } catch (error) {
    title.textContent = "Error";
    selectedRunName.textContent = "Error";
    renderList(metricsEl, [], error.message);
  }
}
