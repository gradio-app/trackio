import { describe, expect, test } from "vitest";
import { visibleLegendEntries } from "./legend.js";

function makeEntries(n) {
  return Array.from({ length: n }, (_, i) => ({
    key: `run-${i}`,
    name: `run-${i}`,
    color: "#000",
  }));
}

describe("visibleLegendEntries", () => {
  test("returns all entries when count is at or below the threshold", () => {
    const entries = makeEntries(6);
    expect(visibleLegendEntries(entries, false, 6)).toEqual(entries);
  });

  test("truncates to the threshold when collapsed and overflowing", () => {
    const entries = makeEntries(10);
    const visible = visibleLegendEntries(entries, false, 6);
    expect(visible).toHaveLength(6);
    expect(visible[0].key).toBe("run-0");
    expect(visible[5].key).toBe("run-5");
  });

  test("returns all entries when expanded, even past the threshold", () => {
    const entries = makeEntries(10);
    expect(visibleLegendEntries(entries, true, 6)).toHaveLength(10);
  });

  test("handles empty or missing input without throwing", () => {
    expect(visibleLegendEntries([], false, 6)).toEqual([]);
    expect(visibleLegendEntries(null, false, 6)).toEqual([]);
  });
});
