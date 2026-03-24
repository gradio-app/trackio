export function getPageFromPath() {
  const path = window.location.pathname.replace(/^\/trackio\/?/, "");
  const clean = path.replace(/^\/+/, "").split("?")[0];
  switch (clean) {
    case "":
    case "metrics":
      return "metrics";
    case "system":
      return "system";
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
    default:
      return "metrics";
  }
}

export function navigateTo(page) {
  const params = new URLSearchParams(window.location.search);
  const pathMap = {
    metrics: "/trackio/",
    system: "/trackio/system",
    media: "/trackio/media",
    reports: "/trackio/reports",
    runs: "/trackio/runs",
    "run-detail": "/trackio/run",
    files: "/trackio/files",
  };
  const path = pathMap[page] || "/trackio/";
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
