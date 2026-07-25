function trackioBase() {
  return window.__trackio_base || "";
}

function stripBase(pathname) {
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

export function setArtifactSelectionParams(name, version, { push = false } = {}) {
  const params = new URLSearchParams(window.location.search);
  params.set("selected_artifact", name);
  params.set("selected_version", `v${version}`);
  params.delete("detail_tab");
  const url = `${window.location.pathname}?${params.toString()}`;
  if (push) {
    window.history.pushState({}, "", url);
  } else {
    window.history.replaceState({}, "", url);
  }
}

export function clearArtifactSelectionParams() {
  const params = new URLSearchParams(window.location.search);
  params.delete("selected_artifact");
  params.delete("selected_version");
  params.delete("detail_tab");
  const search = params.toString();
  const url = search
    ? `${window.location.pathname}?${search}`
    : window.location.pathname;
  window.history.replaceState({}, "", url);
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
  setQueryParam("selected_run_id", runId);
  setQueryParam("selected_run", runName);
  setQueryParam("detail_tab", null);
  navigateTo("run-detail");
}

export function setQueryParam(key, value, { push = false } = {}) {
  const params = new URLSearchParams(window.location.search);
  if (value != null && value !== "") {
    params.set(key, value);
  } else {
    params.delete(key);
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
