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

export function setQueryParam(key, value) {
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
  window.history.replaceState({}, "", url);
}
