import { describe, expect, test } from "vitest";
import { latestOnlySelection, reconcileSelectedRuns } from "./selection.js";

describe("latestOnlySelection", () => {
  test("returns an empty array when there are no runs", () => {
    expect(latestOnlySelection([])).toEqual([]);
    expect(latestOnlySelection(null)).toEqual([]);
    expect(latestOnlySelection(undefined)).toEqual([]);
  });

  test("picks the first run (runs render newest-first in the sidebar)", () => {
    expect(latestOnlySelection(["run-2", "run-1", "run-0"])).toEqual(["run-2"]);
  });

  test("returns the sole run when only one is present", () => {
    expect(latestOnlySelection(["only"])).toEqual(["only"]);
  });
});

describe("reconcileSelectedRuns", () => {
  test("selects all runs when the previous selection was empty (fresh load)", () => {
    expect(reconcileSelectedRuns([], ["a", "b", "c"])).toEqual(["a", "b", "c"]);
  });

  test("keeps a partial selection without auto-selecting new runs", () => {
    expect(reconcileSelectedRuns(["a"], ["a", "b", "c"], ["a", "b"])).toEqual(["a"]);
  });

  test("auto-selects new runs when all previous runs were selected", () => {
    expect(
      reconcileSelectedRuns(["a", "b"], ["a", "b", "c"], ["a", "b"]),
    ).toEqual(["a", "b", "c"]);
  });

  test("preserves the chosen runs when the run list is unchanged on refresh", () => {
    const prev = ["b"];
    const next = ["a", "b", "c"];
    expect(reconcileSelectedRuns(prev, next, next)).toEqual(["b"]);
    expect(reconcileSelectedRuns(["b", "a", "c"], next, next)).toEqual([
      "b",
      "a",
      "c",
    ]);
  });

  test("drops runs that no longer exist on the server", () => {
    expect(
      reconcileSelectedRuns(["a", "b", "c"], ["a", "c"], ["a", "b", "c"]),
    ).toEqual(["a", "c"]);
  });

  test("falls back to all runs when none of the previously selected runs exist anymore", () => {
    expect(reconcileSelectedRuns(["a"], ["b"], ["a"])).toEqual(["b"]);
    expect(
      reconcileSelectedRuns(["x", "y"], ["a", "b", "c"], ["x", "y"]),
    ).toEqual(["a", "b", "c"]);
  });
});
