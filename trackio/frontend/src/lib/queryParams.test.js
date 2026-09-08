import { describe, expect, test } from "vitest";
import {
  AUTO_PANELS_PER_ROW,
  parsePlotsPerRow,
} from "./plotLayout.js";
import { getInitialSidebarState } from "./viewport.js";

describe("plots_per_row", () => {
  test("accepts auto and supported integer values", () => {
    expect(parsePlotsPerRow("auto")).toBe(AUTO_PANELS_PER_ROW);
    expect([1, 2, 3, 4, 5, 6].map((value) => parsePlotsPerRow(String(value))))
      .toEqual([1, 2, 3, 4, 5, 6]);
  });

  test("ignores unsupported values", () => {
    expect([null, "", "0", "7", "2.5", "invalid"].map(parsePlotsPerRow))
      .toEqual([null, null, null, null, null, null]);
  });
});

describe("sidebar", () => {
  test("uses responsive mode for auto, omitted, and invalid values", () => {
    const responsive = { hidden: false, open: true, responsive: true };
    expect(getInitialSidebarState("auto")).toEqual(responsive);
    expect(getInitialSidebarState(null)).toEqual(responsive);
    expect(getInitialSidebarState("invalid")).toEqual(responsive);
  });

  test("maps explicit modes without responsive overrides", () => {
    expect(getInitialSidebarState("visible")).toEqual({
      hidden: false,
      open: true,
      responsive: false,
    });
    expect(getInitialSidebarState("collapsed")).toEqual({
      hidden: false,
      open: false,
      responsive: false,
    });
    expect(getInitialSidebarState("hidden")).toEqual({
      hidden: true,
      open: false,
      responsive: false,
    });
  });
});
