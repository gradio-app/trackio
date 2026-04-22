const projectTitle = document.querySelector("#project-title");
const projectsEl = document.querySelector("#projects");
const runsEl = document.querySelector("#runs");
const metricsEl = document.querySelector("#metrics");

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

function getInitialProject(projects) {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("project");
  if (fromUrl && projects.includes(fromUrl)) {
    return fromUrl;
  }
  return projects[0] || null;
}

function renderProjects(projects, selectedProject) {
  projectsEl.innerHTML = "";
  for (const project of projects) {
    const button = document.createElement("button");
    button.className = `chip${project === selectedProject ? " active" : ""}`;
    button.textContent = project;
    button.addEventListener("click", () => {
      const params = new URLSearchParams(window.location.search);
      params.set("project", project);
      window.location.search = params.toString();
    });
    projectsEl.appendChild(button);
  }
}

function renderRuns(runRecords) {
  runsEl.innerHTML = "";
  if (!runRecords.length) {
    runsEl.innerHTML = '<div class="item"><strong>No runs yet</strong><div class="meta">Log a run and refresh this page.</div></div>';
    return;
  }

  for (const record of runRecords.slice(0, 8)) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `
      <strong>${record.name || "Unnamed run"}</strong>
      <div class="meta">Created: ${record.created_at || "unknown"} | Updated: ${record.updated_at || "unknown"}</div>
    `;
    runsEl.appendChild(item);
  }
}

function renderMetrics(metrics) {
  metricsEl.innerHTML = "";
  if (!metrics.length) {
    metricsEl.innerHTML = '<div class="item"><strong>No metrics yet</strong><div class="meta">This run has not logged any metric names.</div></div>';
    return;
  }

  for (const metric of metrics.slice(0, 12)) {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML = `<strong>${metric}</strong><div class="meta">Use this starter as the place to fetch values and draw charts.</div>`;
    metricsEl.appendChild(item);
  }
}

async function load() {
  try {
    const projects = await api("get_all_projects");
    const selectedProject = getInitialProject(projects);
    projectTitle.textContent = selectedProject || "No local Trackio projects";
    renderProjects(projects, selectedProject);

    if (!selectedProject) {
      renderRuns([]);
      renderMetrics([]);
      return;
    }

    const runRecords = await api("get_runs_for_project", { project: selectedProject });
    renderRuns(runRecords);

    const firstRun = runRecords[0]?.name || null;
    if (!firstRun) {
      renderMetrics([]);
      return;
    }

    const metrics = await api("get_metrics_for_run", {
      project: selectedProject,
      run: firstRun,
    });
    renderMetrics(metrics);
  } catch (error) {
    projectTitle.textContent = "Frontend error";
    runsEl.innerHTML = `<div class="item"><strong>Could not load Trackio data</strong><div class="meta">${error.message}</div></div>`;
    metricsEl.innerHTML = "";
  }
}

load();
