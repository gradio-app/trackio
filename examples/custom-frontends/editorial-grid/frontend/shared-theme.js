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

function createButton(project, selectedProject) {
  const button = document.createElement("button");
  button.className = project === selectedProject ? "active" : "";
  button.textContent = project;
  button.addEventListener("click", () => {
    const params = new URLSearchParams(window.location.search);
    params.set("project", project);
    window.location.search = params.toString();
  });
  return button;
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

export async function mountTheme({ title, projectsEl, runsEl, metricsEl }) {
  try {
    const projects = await api("get_all_projects");
    const params = new URLSearchParams(window.location.search);
    const selectedProject =
      params.get("project") && projects.includes(params.get("project"))
        ? params.get("project")
        : projects[0];

    title.textContent = selectedProject || "No projects";
    projectsEl.innerHTML = "";
    for (const project of projects) {
      projectsEl.appendChild(createButton(project, selectedProject));
    }

    if (!selectedProject) {
      renderList(runsEl, [], "No runs yet");
      renderList(metricsEl, [], "No metrics yet");
      return;
    }

    const runs = await api("get_runs_for_project", { project: selectedProject });
    renderList(
      runsEl,
      runs.slice(0, 8).map((run) => run.name || "Unnamed run"),
      "No runs yet",
    );

    const firstRun = runs[0]?.name;
    if (!firstRun) {
      renderList(metricsEl, [], "No metrics yet");
      return;
    }

    const metrics = await api("get_metrics_for_run", {
      project: selectedProject,
      run: firstRun,
    });
    renderList(metricsEl, metrics.slice(0, 12), "No metrics yet");
  } catch (error) {
    title.textContent = "Error";
    renderList(runsEl, [error.message], "Error");
    renderList(metricsEl, [], "Error");
  }
}
