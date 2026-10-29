import { describe, expect, test } from "vitest";
import { groupMediaByKey } from "./mediaGroups.js";

function item(key, step, run = "run-a", index = step) {
  return { key, step, _run: run, _runId: run, _index: index };
}

describe("groupMediaByKey", () => {
  test("puts the same key from the same run in one group ordered by step", () => {
    const groups = groupMediaByKey([
      item("plot", 20),
      item("plot", 0),
      item("plot", 10),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].items.map((i) => i.step)).toEqual([0, 10, 20]);
  });

  test("keeps different keys and runs in separate groups in input order", () => {
    const groups = groupMediaByKey([
      item("sample", 5, "run-b"),
      item("plot", 5),
      item("sample", 5),
      item("plot", 0),
    ]);
    expect(groups.map((g) => g.items[0].key + "/" + g.items[0]._run)).toEqual([
      "sample/run-b",
      "plot/run-a",
      "sample/run-a",
    ]);
    expect(groups[1].items.map((i) => i.step)).toEqual([0, 5]);
  });

  test("orders entries logged at the same step by log order", () => {
    const groups = groupMediaByKey([item("plot", 1, "run-a", 9), item("plot", 1, "run-a", 3)]);
    expect(groups[0].items.map((i) => i._index)).toEqual([3, 9]);
  });

  test("returns no groups for no items", () => {
    expect(groupMediaByKey([])).toEqual([]);
  });
});
