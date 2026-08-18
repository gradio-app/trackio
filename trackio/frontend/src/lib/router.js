function trackioBase() {
  return window.__trackio_base || "";
}

export function stripBase(pathname) {
  const base = trackioBase();
  if (base && pathname.startsWith(base)) {
    return pathname.slice(base.length) || "/";
  }
  return pathname;
}

export function getPageFromPath() {
  const raw = stripBase(window.location.pathname);
  const pathname = raw.replace(/\/+$/, "") || "/";
  const clean =
    pathname === "/" ? "" : pathname.replace(/^\//, "").split("/")[0];
  switch (clean) {
    case "":
    case "metrics":
      return "metrics";
    case "system":
      return "system";
    case "traces":
      return "traces";
    case "media":
      return "media";
    case "reports":
      return "reports";
    case "runs":
      return "runs";
    case "run":
      return "run-detail";
    case "files":
      return "files";
    case "artifacts":
      return "artifacts";
    case "sweeps":
      return "sweeps";
    case "settings":
      return "settings";
    default:
      return "metrics";
  }
}

export function navigateTo(page) {
  const params = new URLSearchParams(window.location.search);
  const pathMap = {
    metrics: "/",
    traces: "/traces",
    system: "/system",
    media: "/media",
    reports: "/reports",
    runs: "/runs",
    "run-detail": "/run",
    files: "/files",
    artifacts: "/artifacts",
    sweeps: "/sweeps",
    settings: "/settings",
  };
  const path = trackioBase() + (pathMap[page] || "/");
  const search = params.toString();
  const url = search ? `${path}?${search}` : path;
  window.history.pushState({}, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function getQueryParam(key) {
  return new URLSearchParams(window.location.search).get(key);
}

function updateQueryParams(changes, { push = false } = {}) {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(changes)) {
    if (value != null && value !== "") {
      params.set(key, value);
    } else {
      params.delete(key);
    }
  }
  const search = params.toString();
  const url = search
    ? `${window.location.pathname}?${search}`
    : window.location.pathname;
  if (push) {
    window.history.pushState({}, "", url);
  } else {
    window.history.replaceState({}, "", url);
  }
}

export function setArtifactSelectionParams(name, version, { push = false } = {}) {
  updateQueryParams(
    {
      selected_artifact: name,
      selected_version: `v${version}`,
      detail_tab: null,
    },
    { push },
  );
}

export function clearArtifactSelectionParams() {
  updateQueryParams({
    selected_artifact: null,
    selected_version: null,
    detail_tab: null,
  });
}

export function getArtifactSelectionFromUrl() {
  const name = getQueryParam("selected_artifact");
  const verParam = getQueryParam("selected_version");
  const version = verParam
    ? parseInt(String(verParam).replace(/^v/i, ""), 10)
    : NaN;
  return { name, version: Number.isNaN(version) ? null : version };
}

export function openRunDetail(runName, runId) {
  updateQueryParams({
    selected_run_id: runId,
    selected_run: runName,
    detail_tab: null,
  });
  navigateTo("run-detail");
}

export function setQueryParam(key, value, { push = false } = {}) {
  updateQueryParams({ [key]: value }, { push });
}
