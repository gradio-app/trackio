import { describe, expect, test } from "vitest";
import { NARROW_VIEWPORT_QUERY, watchNarrowViewport } from "./viewport.js";

function fakeWindow(initialMatches) {
  const listeners = new Set();
  const query = {
    matches: initialMatches,
    addEventListener: (type, fn) => type === "change" && listeners.add(fn),
    removeEventListener: (type, fn) => type === "change" && listeners.delete(fn),
  };
  return {
    queries: [],
    listenerCount: () => listeners.size,
    cross(matches) {
      query.matches = matches;
      for (const fn of [...listeners]) fn({ matches });
    },
    matchMedia(q) {
      this.queries.push(q);
      return query;
    },
  };
}

describe("watchNarrowViewport", () => {
  test("fires immediately when the viewport is already narrow", () => {
    const win = fakeWindow(true);
    let calls = 0;
    watchNarrowViewport(() => calls++, win);
    expect(calls).toBe(1);
    expect(win.queries).toEqual([NARROW_VIEWPORT_QUERY]);
  });

  test("does not fire on a wide viewport", () => {
    const win = fakeWindow(false);
    let calls = 0;
    watchNarrowViewport(() => calls++, win);
    expect(calls).toBe(0);
  });

  test("fires when the viewport crosses into narrow", () => {
    const win = fakeWindow(false);
    let calls = 0;
    watchNarrowViewport(() => calls++, win);
    win.cross(true);
    expect(calls).toBe(1);
  });

  test("does not fire when the viewport crosses back to wide", () => {
    const win = fakeWindow(true);
    let calls = 0;
    watchNarrowViewport(() => calls++, win);
    win.cross(false);
    expect(calls).toBe(1);
  });

  test("stays quiet while the viewport remains narrow", () => {
    const win = fakeWindow(true);
    let calls = 0;
    watchNarrowViewport(() => calls++, win);
    win.cross(false);
    win.cross(true);
    expect(calls).toBe(2);
  });

  test("removes its listener when stopped", () => {
    const win = fakeWindow(false);
    let calls = 0;
    const stop = watchNarrowViewport(() => calls++, win);
    expect(win.listenerCount()).toBe(1);
    stop();
    expect(win.listenerCount()).toBe(0);
    win.cross(true);
    expect(calls).toBe(0);
  });

  test("is a no-op without matchMedia", () => {
    expect(() => watchNarrowViewport(() => {}, {})()).not.toThrow();
  });
});
