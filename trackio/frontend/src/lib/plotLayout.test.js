import { describe, expect, test } from "vitest";
import {
  AUTO_PANELS_PER_ROW,
  PANELS_PER_ROW_CHOICES,
  getPlotColumns,
  isAutoPanels,
} from "./plotLayout.js";

describe("isAutoPanels", () => {
  test("recognises the auto setting", () => {
    expect(isAutoPanels(AUTO_PANELS_PER_ROW)).toBe(true);
  });

  test("rejects fixed column counts", () => {
    expect(isAutoPanels(4)).toBe(false);
    expect(isAutoPanels("4")).toBe(false);
  });
});

describe("getPlotColumns", () => {
  test("caps a fixed count at the number of plots", () => {
    expect(getPlotColumns(4, 2)).toBe(2);
    expect(getPlotColumns(4, 9)).toBe(4);
  });

  test("never returns fewer than one column", () => {
    expect(getPlotColumns(4, 0)).toBe(1);
    expect(getPlotColumns(0, 3)).toBe(3);
  });

  test("leaves the column count to CSS when auto", () => {
    expect(getPlotColumns(AUTO_PANELS_PER_ROW, 9)).toBe(9);
    expect(getPlotColumns(AUTO_PANELS_PER_ROW, 1)).toBe(1);
  });

  test("does not produce NaN for non-numeric settings", () => {
    expect(getPlotColumns(undefined, 3)).toBe(3);
    expect(getPlotColumns("nonsense", 3)).toBe(3);
  });
});

describe("PANELS_PER_ROW_CHOICES", () => {
  test("offers auto first, then the fixed counts", () => {
    expect(PANELS_PER_ROW_CHOICES[0]).toEqual({
      label: "Auto",
      value: AUTO_PANELS_PER_ROW,
    });
    expect(PANELS_PER_ROW_CHOICES.slice(1)).toEqual([1, 2, 3, 4, 5, 6]);
  });
});
