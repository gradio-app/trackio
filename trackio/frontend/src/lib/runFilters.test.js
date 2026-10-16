import { expect, it } from "vitest";
import { configFilterKeys, compileConfigFilter, filterRunsByConfig } from "./runFilters.js";
const rule = (key, value, operator = "=") => ({ key: JSON.stringify(key), value, operator });
it("matches OR groups of AND conditions by ID despite duplicate names", () => {
  const runs = Array.from({ length: 4 }, (_, id) => ({ id, name: "same" }));
  const configs = Object.fromEntries(runs.map((run, i) => [run.id, { batch_size: i < 2 ? 32 : 64, optimizer: i % 2 ? "sgd" : "adam" }]));
  const match = compileConfigFilter([[rule(["batch_size"], "32"), rule(["optimizer"], "adam")], [rule(["batch_size"], "64"), rule(["optimizer"], "sgd")]]);
  expect(filterRunsByConfig(runs, configs, match)).toEqual([runs[0], runs[3]]);
});
it("distinguishes nested paths from literal dotted keys", () => {
  const config = { dataset: { augment: true }, "dataset.augment": false, _private: 1, list: [1], nullable: null };
  expect(configFilterKeys({ a: config }).map((key) => JSON.parse(key.value))).toEqual([["dataset", "augment"], ["dataset.augment"], ["nullable"]]);
  expect(compileConfigFilter([[rule(["dataset", "augment"], "true")]])(config)).toBe(true);
  expect(compileConfigFilter([[rule(["dataset.augment"], "true")]])(config)).toBe(false);
});
it.each([">", ">=", "<", "<="])("compares numbers using %s without coercing other types", (operator) => {
  const match = compileConfigFilter([[rule(["size"], "32", operator)]]);
  const number = operator.startsWith(">") ? 64 : 16;
  expect(match({ size: number })).toBe(true);
  expect(match({ size: String(number) })).toBe(false);
  expect(match({ size: null })).toBe(false);
  expect(compileConfigFilter([[rule(["size"], "", operator)]])({ size: number })).toBe(false);
});
it("handles missing keys, nulls, empty strings, inequality and contains", () => {
  expect(compileConfigFilter([[rule(["a"], "x", "!=")]])({})).toBe(false);
  expect(compileConfigFilter([[rule(["a"], "null")]])({ a: null })).toBe(true);
  expect(compileConfigFilter([[rule(["a"], "32.0")]])({ a: 32 })).toBe(true);
  expect(compileConfigFilter([[rule(["a"], "")]])({ a: "" })).toBe(true);
  expect(compileConfigFilter([[rule(["a"], "adam", "contains")]])({ a: "adamw" })).toBe(true);
  expect(compileConfigFilter([[rule(["a"], "2", "contains")]])({ a: 32 })).toBe(false);
});
it("ignores unfinished rows and supports legacy configs", () => {
  const runs = [{ name: "legacy" }];
  const groups = [[{ key: "", value: "", operator: "=" }]];
  expect(filterRunsByConfig(runs, {}, compileConfigFilter(groups))).toEqual(runs);
  groups.push([rule(["size"], "32")]);
  expect(filterRunsByConfig(runs, { legacy: { size: 64 } }, compileConfigFilter(groups))).toEqual([]);
  expect(filterRunsByConfig(runs, { legacy: { size: 32 } }, compileConfigFilter(groups))).toEqual(runs);
});
