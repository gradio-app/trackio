import { afterEach, describe, expect, it } from "vitest";
import {
  EMBED_PROTOCOL,
  buildSnapshot,
  buildViewUrl,
  registerSnapshotProvider,
  startEmbedBridge,
} from "./embedBridge.js";

function fakeWindow() {
  const listeners = [];
  const parentMessages = [];
  const parent = {
    postMessage: (message, origin) => parentMessages.push({ message, origin }),
  };
  return {
    parent,
    parentMessages,
    addEventListener: (type, fn) => listeners.push(fn),
    removeEventListener: (type, fn) => listeners.splice(listeners.indexOf(fn), 1),
    dispatch: (event) => listeners.forEach((fn) => fn(event)),
    listenerCount: () => listeners.length,
  };
}

const location = { href: "https://me-dash.hf.space/?sidebar=hidden&__theme=dark&xmin=1&xmax=2" };

let cleanups = [];
afterEach(() => {
  cleanups.forEach((fn) => fn());
  cleanups = [];
});

describe("buildSnapshot", () => {
  it("merges the app and metrics providers into one view", () => {
    cleanups.push(
      registerSnapshotProvider("app", () => ({
        page: "metrics",
        project: "mnist",
        runs: [{ name: "run-1", id: "abc" }],
        x_axis: "step",
        smoothing: 10,
        metric_filter: "",
      })),
      registerSnapshotProvider("metrics", () => ({
        x_axis: "step",
        x_range: [100, 400],
        metrics: ["train/loss", "train/acc"],
        metrics_on_screen: ["train/loss"],
        latest_x: 900,
      })),
    );

    const snap = buildSnapshot({ location, now: new Date("2026-09-24T00:00:00Z") });

    expect(snap).toMatchObject({
      project: "mnist",
      runs: [{ name: "run-1", id: "abc" }],
      x_axis: "step",
      x_range: [100, 400],
      metrics: ["train/loss", "train/acc"],
      metrics_on_screen: ["train/loss"],
      latest_x: 900,
      metric_filter: null,
      captured_at: "2026-09-24T00:00:00.000Z",
    });
    const url = new URL(snap.view_url);
    expect(url.searchParams.get("xmin")).toBe("100");
    expect(url.searchParams.get("xmax")).toBe("400");
    expect(url.searchParams.get("run_ids")).toBe("abc");
    expect(url.searchParams.get("sidebar")).toBe("hidden");
  });

  it("reports an unzoomed view as a null range", () => {
    const url = new URL(buildViewUrl(location, { project: "p", x_range: null, runs: [] }));
    expect(url.searchParams.has("xmin")).toBe(false);
    expect(url.searchParams.has("xmax")).toBe(false);
  });
});

describe("startEmbedBridge", () => {
  it("announces itself to the parent and answers getState to the asker only", () => {
    const win = fakeWindow();
    cleanups.push(startEmbedBridge({ win, snapshot: () => ({ project: "p" }) }));

    expect(win.parentMessages[0].message).toMatchObject({
      protocol: EMBED_PROTOCOL,
      type: "ready",
      version: 1,
    });

    const replies = [];
    win.dispatch({
      data: { protocol: EMBED_PROTOCOL, type: "getState", id: 7 },
      source: Object.assign(win.parent, {
        postMessage: (message, origin) => replies.push({ message, origin }),
      }),
      origin: "http://localhost:5173",
    });

    expect(replies).toEqual([
      {
        message: {
          protocol: EMBED_PROTOCOL,
          version: 1,
          type: "state",
          id: 7,
          state: { project: "p" },
        },
        origin: "http://localhost:5173",
      },
    ]);
  });

  it("ignores messages that are not from its parent or not in the protocol", () => {
    const win = fakeWindow();
    let asked = 0;
    cleanups.push(startEmbedBridge({ win, snapshot: () => (asked++, {}) }));

    const stranger = { postMessage: () => {} };
    win.dispatch({ data: { protocol: EMBED_PROTOCOL, type: "getState" }, source: stranger, origin: "x" });
    win.dispatch({ data: { type: "getState" }, source: win.parent, origin: "x" });

    expect(asked).toBe(0);
  });

  it("does nothing when the dashboard is not embedded", () => {
    const win = fakeWindow();
    win.parent = win;
    startEmbedBridge({ win });
    expect(win.listenerCount()).toBe(0);
  });
});
