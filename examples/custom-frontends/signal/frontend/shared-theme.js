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

function updateQueryParam(key, value) {
  const params = new URLSearchParams(window.location.search);
  if (value) {
    params.set(key, value);
  } else {
    params.delete(key);
  }
  window.location.search = params.toString();
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

function renderEmptyState(element, message) {
  element.innerHTML = "";
  const item = document.createElement("div");
  item.className = "item";
  item.textContent = message;
  element.appendChild(item);
}

function formatTimestamp(value) {
  if (!value) {
    return "unknown";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString();
}

function summarizeMessages(messages) {
  if (!Array.isArray(messages) || !messages.length) {
    return "No messages";
  }
  return messages
    .slice(0, 3)
    .map((message) => {
      const role = message.role || "unknown";
      const content = Array.isArray(message.content)
        ? message.content
            .map((part) => part.text || part.caption || part.type || "[content]")
            .join(" ")
        : String(message.content || "");
      return `${role}: ${content}`.trim();
    })
    .join("\n");
}

function renderTraceCard(trace) {
  const card = document.createElement("article");
  card.className = "trace-card";

  const header = document.createElement("div");
  header.className = "trace-header";

  const heading = document.createElement("div");
  heading.className = "trace-heading";
  heading.textContent =
    trace.metadata?.label || trace.name || trace.key || "Trace event";

  const step = document.createElement("div");
  step.className = "trace-step";
  step.textContent = `Step ${trace.step ?? "?"}`;

  header.appendChild(heading);
  header.appendChild(step);

  const meta = document.createElement("div");
  meta.className = "trace-meta";
  meta.textContent = `${formatTimestamp(trace.timestamp)} | ${trace.messages?.length || 0} messages`;

  const transcript = document.createElement("pre");
  transcript.className = "trace-transcript";
  transcript.textContent = summarizeMessages(trace.messages);

  card.appendChild(header);
  card.appendChild(meta);
  card.appendChild(transcript);

  if (trace.metadata && Object.keys(trace.metadata).length) {
    const tags = document.createElement("div");
    tags.className = "trace-tags";
    for (const [key, value] of Object.entries(trace.metadata)) {
      const tag = document.createElement("span");
      tag.className = "trace-tag";
      tag.textContent = `${key}: ${value}`;
      tags.appendChild(tag);
    }
    card.appendChild(tags);
  }

  return card;
}

async function renderTraces(element, project, run) {
  element.innerHTML = "";
  const traces = await api("get_traces", {
    project,
    run: run.name,
    run_id: run.id,
    sort: "request_time_desc",
    limit: 12,
  });

  if (!traces.length) {
    renderEmptyState(element, "No traces logged for this run.");
    return 0;
  }

  const list = document.createElement("div");
  list.className = "trace-list";
  for (const trace of traces) {
    list.appendChild(renderTraceCard(trace));
  }
  element.appendChild(list);
  return traces.length;
}

export async function mountTheme({
  title,
  projectSelect,
  runSelect,
  metricsEl,
  metricsSubtitle,
  statusLine,
}) {
  try {
    const projects = await api("get_all_projects");
    const params = new URLSearchParams(window.location.search);
    const selectedProject =
      params.get("project") && projects.includes(params.get("project"))
        ? params.get("project")
        : projects[0];

    title.textContent = selectedProject || "No project";
    statusLine.textContent = selectedProject
      ? "Traces loaded from /api/get_traces. Metrics are intentionally ignored here."
      : "Pick a project.";

    renderOptions(
      projectSelect,
      projects.map((project) => ({ value: project })),
      selectedProject,
      (option) => option.value,
    );
    projectSelect.onchange = () => updateQueryParam("project", projectSelect.value);

    if (!selectedProject) {
      renderEmptyState(metricsEl, "No traces yet");
      return;
    }

    const runs = await api("get_runs_for_project", { project: selectedProject });
    if (!runs.length) {
      runSelect.innerHTML = "";
      renderEmptyState(metricsEl, "No traces yet");
      return;
    }

    const paramsRunId = params.get("run_id");
    let selectedRun = runs.find((run) => run.id === paramsRunId) || runs[0];
    renderOptions(
      runSelect,
      runs.map((run) => ({ value: run.id, name: run.name || "Unnamed run" })),
      selectedRun.id,
      (option) => option.name,
    );

    const updateSelectedRun = async (runId) => {
      selectedRun = runs.find((run) => run.id === runId) || runs[0];
      runSelect.value = selectedRun.id;
      metricsSubtitle.textContent = `Recent traces for ${selectedRun.name || "the selected run"}.`;
      await renderTraces(metricsEl, selectedProject, selectedRun);
    };

    runSelect.onchange = () => updateQueryParam("run_id", runSelect.value);
    await updateSelectedRun(selectedRun.id);
  } catch (error) {
    title.textContent = "Error";
    renderEmptyState(metricsEl, error.message);
  }
}
