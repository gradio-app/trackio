import { describe, expect, it } from "vitest";
import { DEFAULT_COLORS, buildColorMap } from "./stores.js";

describe("buildColorMap", () => {
  const newestFirst = (n) =>
    Array.from({ length: n }, (_, i) => ({ id: `id-${n - i}`, name: `run-${n - i}` }));

  it("gives the oldest run the first palette color", () => {
    const map = buildColorMap(newestFirst(3));
    expect(map["id-1"]).toBe(DEFAULT_COLORS[0]);
    expect(map["id-2"]).toBe(DEFAULT_COLORS[1]);
    expect(map["id-3"]).toBe(DEFAULT_COLORS[2]);
  });

  it("keeps existing run colors when a new run is added", () => {
    const before = buildColorMap(newestFirst(3));
    const after = buildColorMap(newestFirst(4));
    for (const key of Object.keys(before)) {
      expect(after[key]).toBe(before[key]);
    }
    expect(after["id-4"]).toBe(DEFAULT_COLORS[3]);
  });

  it("keys string runs by name", () => {
    expect(buildColorMap(["b", "a"])).toEqual({
      a: DEFAULT_COLORS[0],
      b: DEFAULT_COLORS[1],
    });
  });
});
