import { describe, expect, test } from "vitest";
import {
  buildComparerRows,
  filterComparerRows,
  flattenConfig,
  formatCellValue,
  rowDiffers,
  runKeyOf,
} from "./comparer.js";

describe("runKeyOf", () => {
  test("prefers id and falls back to name", () => {
    expect(runKeyOf({ id: "abc", name: "run-a" })).toBe("abc");
    expect(runKeyOf({ name: "run-a" })).toBe("run-a");
    expect(runKeyOf(null)).toBeUndefined();
  });
});

describe("flattenConfig", () => {
  test("keeps flat configs unchanged", () => {
    expect(flattenConfig({ lr: 0.01, model: "resnet" })).toEqual({
      lr: 0.01,
      model: "resnet",
    });
  });

  test("flattens nested objects to dot paths", () => {
    expect(
      flattenConfig({ optimizer: { name: "adam", lr: { initial: 0.1 } } }),
    ).toEqual({
      "optimizer.name": "adam",
      "optimizer.lr.initial": 0.1,
    });
  });

  test("keeps arrays as leaf values", () => {
    const tags = ["a", { b: 1 }];
    expect(flattenConfig({ tags })).toEqual({ tags });
  });

  test("keeps null leaves", () => {
    expect(flattenConfig({ a: null })).toEqual({ a: null });
  });

  test("drops empty object leaves", () => {
    expect(flattenConfig({ a: {}, b: 1 })).toEqual({ b: 1 });
  });

  test("returns an empty object for non-object input", () => {
    expect(flattenConfig(null)).toEqual({});
    expect(flattenConfig(undefined)).toEqual({});
    expect(flattenConfig("nope")).toEqual({});
    expect(flattenConfig(42)).toEqual({});
    expect(flattenConfig(["a"])).toEqual({});
  });

  test("coerces safe bigint leaves to numbers and keeps big ones exact", () => {
    expect(flattenConfig({ steps: 5n, nested: { n: 2n } })).toEqual({
      steps: 5,
      "nested.n": 2,
    });
    expect(flattenConfig({ big: 9223372036854775807n })).toEqual({
      big: "9223372036854775807",
    });
  });

  test("keeps empty-string keys distinct from top-level keys", () => {
    expect(flattenConfig({ "": { lr: 1 }, lr: 2 })).toEqual({
      ".lr": 1,
      lr: 2,
    });
  });

  test("keeps own __proto__ keys as data", () => {
    const flat = flattenConfig(JSON.parse('{"__proto__": 7, "a": 1}'));
    expect(Object.keys(flat)).toEqual(["__proto__", "a"]);
    expect(flat["__proto__"]).toBe(7);
  });

  test("keeps non-plain objects as leaf values", () => {
    const when = new Date("2026-01-01T00:00:00Z");
    const lookup = new Map([["k", 1]]);
    expect(flattenConfig({ when, nested: { lookup } })).toEqual({
      when,
      "nested.lookup": lookup,
    });
  });

  test("keeps literal dotted keys distinct from nested paths", () => {
    expect(flattenConfig({ "a.b": 1, a: { b: 2 } })).toEqual({
      "a\\.b": 1,
      "a.b": 2,
    });
    expect(flattenConfig({ "a.b": { c: 1 } })).toEqual({ "a\\.b.c": 1 });
    expect(flattenConfig({ "a\\b": 1 })).toEqual({ "a\\\\b": 1 });
  });
});

describe("rowDiffers", () => {
  test("false when all values are equal", () => {
    expect(rowDiffers([1, 1, 1], 3)).toBe(false);
    expect(rowDiffers(["a", "a"], 2)).toBe(false);
  });

  test("true when any value differs", () => {
    expect(rowDiffers([1, 2, 1], 3)).toBe(true);
  });

  test("missing counts as different from present", () => {
    expect(rowDiffers([1, undefined], 2)).toBe(true);
  });

  test("false when all values are missing", () => {
    expect(rowDiffers([undefined, undefined], 2)).toBe(false);
  });

  test("null differs from missing and from the string null", () => {
    expect(rowDiffers([null, undefined], 2)).toBe(true);
    expect(rowDiffers([null, "null"], 2)).toBe(true);
    expect(rowDiffers([null, null], 2)).toBe(false);
  });

  test("does not coerce across types", () => {
    expect(rowDiffers([1, "1"], 2)).toBe(true);
    expect(rowDiffers([true, "true"], 2)).toBe(true);
  });

  test("deep-equal objects match regardless of key order", () => {
    const a = { x: 1, nested: { y: 2, z: 3 } };
    const b = { nested: { z: 3, y: 2 }, x: 1 };
    expect(rowDiffers([a, b], 2)).toBe(false);
  });

  test("arrays compare by content and order", () => {
    expect(rowDiffers([["a", "b"], ["a", "b"]], 2)).toBe(false);
    expect(rowDiffers([["a", "b"], ["b", "a"]], 2)).toBe(true);
  });

  test("NaN equals NaN", () => {
    expect(rowDiffers([NaN, NaN], 2)).toBe(false);
    expect(rowDiffers([NaN, 1], 2)).toBe(true);
  });

  test("bigint equals the same number", () => {
    expect(rowDiffers([2n, 2], 2)).toBe(false);
    expect(rowDiffers([9223372036854775806n, 9223372036854775807n], 2)).toBe(
      true,
    );
  });

  test("dates compare by instant, not identity", () => {
    expect(
      rowDiffers([new Date("2026-01-01"), new Date("2026-01-01")], 2),
    ).toBe(false);
    expect(
      rowDiffers([new Date("2026-01-01"), new Date("2026-01-02")], 2),
    ).toBe(true);
  });
});

describe("buildComparerRows", () => {
  const runs = [
    { id: "id-a", name: "run-a" },
    { id: "id-b", name: "run-b" },
  ];

  test("orders sections config then metadata", () => {
    const rows = buildComparerRows(runs, {
      "id-a": { lr: 0.01, _Created: "2026-01-01" },
      "id-b": { lr: 0.02, _Created: "2026-01-02" },
    });
    expect(rows.map((r) => r.section)).toEqual(["config", "metadata"]);
  });

  test("unions and sorts config keys, leaving missing slots undefined", () => {
    const rows = buildComparerRows(runs, {
      "id-a": { seed: 42, optimizer: { name: "adam" } },
      "id-b": { lr: 0.02 },
    });
    expect(rows.map((r) => r.key)).toEqual(["lr", "optimizer.name", "seed"]);
    const lrRow = rows.find((r) => r.key === "lr");
    expect(lrRow.values).toEqual([undefined, 0.02]);
    expect(lrRow.differs).toBe(true);
  });

  test("promotes underscore keys to metadata with display labels", () => {
    const rows = buildComparerRows(runs, {
      "id-a": { lr: 0.01, _Created: "t0", _Group: "exp", _Username: "u" },
      "id-b": { lr: 0.01, _Created: "t1", _Group: "exp", _Username: "u" },
    });
    const configKeys = rows
      .filter((r) => r.section === "config")
      .map((r) => r.key);
    expect(configKeys).toEqual(["lr"]);
    const metadata = rows.filter((r) => r.section === "metadata");
    expect(metadata.map((r) => r.label)).toEqual([
      "Created",
      "Group",
      "Username",
    ]);
    expect(metadata.find((r) => r.label === "Created").differs).toBe(true);
    expect(metadata.find((r) => r.label === "Group").differs).toBe(false);
  });

  test("omits metadata rows when no run has a value", () => {
    const rows = buildComparerRows(runs, {
      "id-a": { lr: 0.01, _Group: null },
      "id-b": { lr: 0.02 },
    });
    expect(rows.filter((r) => r.section === "metadata")).toEqual([]);
  });

  test("treats null metadata values as missing", () => {
    const rows = buildComparerRows(runs, {
      "id-a": { lr: 0.01, _Group: null },
      "id-b": { lr: 0.01, _Group: "demo" },
    });
    const groupRow = rows.find((r) => r.label === "Group");
    expect(groupRow.values).toEqual([undefined, "demo"]);
    expect(groupRow.differs).toBe(true);
  });

  test("resolves configs by id first, then name", () => {
    const rows = buildComparerRows(runs, {
      "id-a": { lr: 0.01 },
      "run-b": { lr: 0.02 },
    });
    expect(rows[0].values).toEqual([0.01, 0.02]);
  });

  test("tolerates malformed config entries", () => {
    const rows = buildComparerRows(runs, {
      "id-a": "junk",
      "id-b": { lr: 1 },
    });
    expect(rows).toEqual([
      {
        section: "config",
        key: "lr",
        label: "lr",
        values: [undefined, 1],
        differs: true,
      },
    ]);
  });
});

describe("filterComparerRows", () => {
  const rows = [
    {
      section: "config",
      key: "optimizer.lr",
      label: "optimizer.lr",
      values: [0.1, 0.2],
      differs: true,
    },
    {
      section: "config",
      key: "seed",
      label: "seed",
      values: [42, 42],
      differs: false,
    },
    {
      section: "metadata",
      key: "_Created",
      label: "Created",
      values: ["t0", "t0"],
      differs: false,
    },
  ];

  test("matches keys case-insensitively", () => {
    expect(filterComparerRows(rows, "OPTIM", false)).toHaveLength(1);
    expect(filterComparerRows(rows, "optimizer.lr", false)).toHaveLength(1);
  });

  test("matches metadata display labels", () => {
    const filtered = filterComparerRows(rows, "created", false);
    expect(filtered).toHaveLength(1);
    expect(filtered[0].key).toBe("_Created");
  });

  test("never matches values", () => {
    expect(filterComparerRows(rows, "42", false)).toHaveLength(0);
  });

  test("diff only keeps differing rows", () => {
    const filtered = filterComparerRows(rows, "", true);
    expect(filtered.map((r) => r.key)).toEqual(["optimizer.lr"]);
  });

  test("search and diff only compose", () => {
    expect(filterComparerRows(rows, "seed", true)).toHaveLength(0);
  });

  test("blank search returns all rows", () => {
    expect(filterComparerRows(rows, "", false)).toHaveLength(3);
    expect(filterComparerRows(rows, "   ", false)).toHaveLength(3);
  });
});

describe("formatCellValue", () => {
  test("marks missing values", () => {
    expect(formatCellValue(undefined)).toEqual({ text: "", missing: true });
  });

  test("renders null as text", () => {
    expect(formatCellValue(null)).toEqual({ text: "null", missing: false });
  });

  test("renders primitives as strings", () => {
    expect(formatCellValue(0.01).text).toBe("0.01");
    expect(formatCellValue(true).text).toBe("true");
    expect(formatCellValue("adam").text).toBe("adam");
    expect(formatCellValue(7n).text).toBe("7");
  });

  test("renders arrays and objects as JSON", () => {
    expect(formatCellValue(["a", 1]).text).toBe('["a",1]');
    expect(formatCellValue({ a: 1 }).text).toBe('{"a":1}');
  });

  test("coerces bigints inside arrays", () => {
    expect(formatCellValue([1n, 2n]).text).toBe("[1,2]");
    expect(formatCellValue([9223372036854775807n]).text).toBe(
      '["9223372036854775807"]',
    );
  });

  test("renders deep-equal objects identically regardless of key order", () => {
    const a = { x: 1, nested: { y: 2, z: 3 } };
    const b = { nested: { z: 3, y: 2 }, x: 1 };
    expect(rowDiffers([a, b], 2)).toBe(false);
    expect(formatCellValue(a).text).toBe(formatCellValue(b).text);
    expect(formatCellValue(b).text).toBe('{"nested":{"y":2,"z":3},"x":1}');
  });

  test("quotes strings that could be mistaken for another type", () => {
    expect(formatCellValue("1").text).toBe('"1"');
    expect(formatCellValue(1).text).toBe("1");
    expect(formatCellValue("0.01").text).toBe('"0.01"');
    expect(formatCellValue("NaN").text).toBe('"NaN"');
    expect(formatCellValue("true").text).toBe('"true"');
    expect(formatCellValue("null").text).toBe('"null"');
    expect(formatCellValue('{"a":1}').text).toBe('"{\\"a\\":1}"');
    expect(formatCellValue("[1,2]").text).toBe('"[1,2]"');
  });

  test("quotes empty and whitespace-padded strings", () => {
    expect(formatCellValue("").text).toBe('""');
    expect(formatCellValue(" adam").text).toBe('" adam"');
    expect(formatCellValue("adam ").text).toBe('"adam "');
  });

  test("keeps ordinary strings unquoted", () => {
    expect(formatCellValue("adam").text).toBe("adam");
    expect(formatCellValue("v1.2.3").text).toBe("v1.2.3");
    expect(formatCellValue("0.010").text).toBe("0.010");
    expect(formatCellValue("resnet-50").text).toBe("resnet-50");
  });
});
