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
  test("reports the starting width immediately", () => {
    const win = fakeWindow(true);
    const seen = [];
    watchNarrowViewport((narrow) => seen.push(narrow), win);
    expect(seen).toEqual([true]);
    expect(win.queries).toEqual([NARROW_VIEWPORT_QUERY]);
  });

  test("reports a wide start too", () => {
    const win = fakeWindow(false);
    const seen = [];
    watchNarrowViewport((narrow) => seen.push(narrow), win);
    expect(seen).toEqual([false]);
  });

  test("reports crossings in both directions", () => {
    const win = fakeWindow(false);
    const seen = [];
    watchNarrowViewport((narrow) => seen.push(narrow), win);
    win.cross(true);
    win.cross(false);
    expect(seen).toEqual([false, true, false]);
  });

  test("removes its listener when stopped", () => {
    const win = fakeWindow(false);
    const seen = [];
    const stop = watchNarrowViewport((narrow) => seen.push(narrow), win);
    expect(win.listenerCount()).toBe(1);
    stop();
    expect(win.listenerCount()).toBe(0);
    win.cross(true);
    expect(seen).toEqual([false]);
  });

  test("is a no-op without matchMedia", () => {
    expect(() => watchNarrowViewport(() => {}, {})()).not.toThrow();
  });
});
