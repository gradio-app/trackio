export const EMBED_PROTOCOL = "trackio-embed";
export const EMBED_PROTOCOL_VERSION = 1;

const providers = new Map();

export function registerSnapshotProvider(name, provider) {
  providers.set(name, provider);
  return () => {
    if (providers.get(name) === provider) providers.delete(name);
  };
}

export function collectSnapshot() {
  const state = {};
  for (const [name, provider] of providers) {
    try {
      const part = provider();
      if (part) state[name] = part;
    } catch (error) {
      state[name] = { error: String(error) };
    }
  }
  return state;
}

export function buildViewUrl(location, view) {
  const url = new URL(location.href);
  const params = url.searchParams;
  for (const key of [
    "project",
    "selected_project",
    "run_ids",
    "runs",
    "x_axis",
    "x-axis",
    "xmin",
    "xmax",
    "smoothing",
    "metric_filter",
    "metrics",
  ]) {
    params.delete(key);
  }
  if (view.project) params.set("project", view.project);
  if (view.runs?.length) {
    params.set("run_ids", view.runs.map((r) => r.id ?? r.name).join(","));
  }
  if (view.x_axis) params.set("x_axis", view.x_axis);
  if (view.x_range) {
    params.set("xmin", String(view.x_range[0]));
    params.set("xmax", String(view.x_range[1]));
  }
  if (view.smoothing != null) params.set("smoothing", String(view.smoothing));
  if (view.metric_filter) params.set("metric_filter", view.metric_filter);
  return url.toString();
}

export function buildSnapshot({ location = window.location, now = new Date() } = {}) {
  const parts = collectSnapshot();
  const app = parts.app || {};
  const metrics = parts.metrics || {};
  const view = {
    page: app.page ?? null,
    project: app.project ?? null,
    space_id: app.space_id ?? null,
    runs: app.runs ?? [],
    x_axis: metrics.x_axis ?? app.x_axis ?? "step",
    x_range: metrics.x_range ?? null,
    smoothing: app.smoothing ?? null,
    log_x: app.log_x ?? false,
    log_y: app.log_y ?? false,
    metric_filter: app.metric_filter || null,
    metrics: metrics.metrics ?? [],
    metrics_on_screen: metrics.metrics_on_screen ?? [],
    latest_x: metrics.latest_x ?? null,
  };
  return {
    ...view,
    captured_at: now.toISOString(),
    view_url: buildViewUrl(location, view),
  };
}

function readSafely(read) {
  try {
    return read();
  } catch {
    return null;
  }
}

function announceTargets(win) {
  const parent = readSafely(() => win.parent);
  const opener = readSafely(() => win.opener);
  const targets = [];
  if (parent && parent !== win) targets.push(parent);
  if (opener && opener !== parent) targets.push(opener);
  return targets;
}

export function startEmbedBridge({ win = window, snapshot = buildSnapshot } = {}) {
  function onMessage(event) {
    const msg = event.data;
    if (!msg || msg.protocol !== EMBED_PROTOCOL) return;
    if (msg.type !== "getState" || !event.source) return;
    let reply;
    try {
      reply = {
        protocol: EMBED_PROTOCOL,
        version: EMBED_PROTOCOL_VERSION,
        type: "state",
        id: msg.id ?? null,
        state: snapshot(),
      };
    } catch (error) {
      reply = {
        protocol: EMBED_PROTOCOL,
        version: EMBED_PROTOCOL_VERSION,
        type: "error",
        id: msg.id ?? null,
        error: String(error),
      };
    }
    event.source.postMessage(reply, event.origin && event.origin !== "null" ? event.origin : "*");
  }

  win.addEventListener("message", onMessage);
  const api = { getViewState: () => snapshot(), protocolVersion: EMBED_PROTOCOL_VERSION };
  win.trackio = Object.assign(win.trackio || {}, api);

  for (const target of announceTargets(win)) {
    target.postMessage(
      {
        protocol: EMBED_PROTOCOL,
        version: EMBED_PROTOCOL_VERSION,
        type: "ready",
        capabilities: ["getState"],
      },
      "*",
    );
  }
  return () => {
    win.removeEventListener("message", onMessage);
    if (win.trackio?.getViewState === api.getViewState) {
      delete win.trackio.getViewState;
      delete win.trackio.protocolVersion;
    }
  };
}
