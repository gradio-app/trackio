import { afterEach, describe, expect, it } from "vitest";
import {
  VIEW_PROTOCOL,
  buildSnapshot,
  registerSnapshotProvider,
  startViewStateBridge,
} from "./viewState.js";

function fakeWindow() {
  const listeners = [];
  return {
    addEventListener: (type, fn) => listeners.push(fn),
    removeEventListener: (type, fn) => listeners.splice(listeners.indexOf(fn), 1),
    dispatch: (event) => listeners.forEach((fn) => fn(event)),
    listenerCount: () => listeners.length,
  };
}

function recorder() {
  const messages = [];
  return { messages, postMessage: (message, origin) => messages.push({ message, origin }) };
}

let cleanups = [];
afterEach(() => {
  cleanups.forEach((fn) => fn());
  cleanups = [];
});

describe("buildSnapshot", () => {
  it("merges the registered providers and builds a view_url that reproduces the view", () => {
    cleanups.push(
      registerSnapshotProvider("app", () => ({
        project: "mnist",
        runs: [{ name: "run-1", id: "abc" }],
        smoothing: 10,
      })),
      registerSnapshotProvider("metrics", () => ({
        x_axis: "step",
        x_range: [100, 400],
        metrics: ["train/loss", "train/acc"],
        metrics_on_screen: ["train/loss"],
      })),
    );

    const snap = buildSnapshot({
      location: { href: "https://me-dash.hf.space/?sidebar=hidden&xmin=1&xmax=2" },
    });

    expect(snap).toMatchObject({
      project: "mnist",
      x_range: [100, 400],
      metrics_on_screen: ["train/loss"],
    });
    const params = new URL(snap.view_url).searchParams;
    expect(Object.fromEntries(params)).toMatchObject({
      sidebar: "hidden",
      project: "mnist",
      run_ids: "abc",
      xmin: "100",
      xmax: "400",
    });
  });
});

describe("startViewStateBridge", () => {
  it("announces itself, and answers getState to whoever asked at their origin", () => {
    const win = fakeWindow();
    win.parent = recorder();
    cleanups.push(startViewStateBridge({ win, snapshot: () => ({ project: "p" }) }));
    expect(win.parent.messages[0].message).toMatchObject({ protocol: VIEW_PROTOCOL, type: "ready" });

    const asker = recorder();
    win.dispatch({ data: { protocol: VIEW_PROTOCOL, type: "getState", id: 7 }, source: asker, origin: "https://x.dev" });
    win.dispatch({ data: { type: "getState" }, source: asker, origin: "https://x.dev" });

    expect(asker.messages).toEqual([
      {
        message: { protocol: VIEW_PROTOCOL, version: 1, type: "state", id: 7, state: { project: "p" } },
        origin: "https://x.dev",
      },
    ]);
  });

  it("works outside a frame through window.trackio, and cleans up after itself", () => {
    const win = fakeWindow();
    win.parent = win;
    win.opener = recorder();
    const stop = startViewStateBridge({ win, snapshot: () => ({ project: "p" }) });

    expect(win.trackio.getViewState()).toEqual({ project: "p" });
    expect(win.opener.messages[0].message).toMatchObject({ type: "ready" });

    stop();
    expect(win.trackio.getViewState).toBeUndefined();
    expect(win.listenerCount()).toBe(0);
  });
});
