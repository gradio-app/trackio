import { describe, expect, it } from "vitest";
import {
  describeParamSpec,
  flattenParameterSpecs,
  sweepParamSpecs,
  sweepTotalTrials,
  trialParamKeys,
} from "./sweeps.js";

describe("flattenParameterSpecs", () => {
  it("flattens nested parameters to dotted paths", () => {
    const flat = flattenParameterSpecs({
      lr: { values: [0.1, 0.01] },
      optimizer: { parameters: { momentum: { min: 0, max: 1 } } },
    });
    expect(Object.keys(flat)).toEqual(["lr", "optimizer.momentum"]);
  });

  it("wraps bare values as constant specs", () => {
    expect(flattenParameterSpecs({ epochs: 5 })).toEqual({
      epochs: { value: 5 },
    });
  });
});

describe("sweepTotalTrials", () => {
  it("computes the grid product across parameters", () => {
    const total = sweepTotalTrials({
      method: "grid",
      parameters: {
        lr: { values: [0.1, 0.01, 0.001] },
        batch: { values: [16, 32] },
        seed: { value: 42 },
      },
    });
    expect(total).toBe(6);
  });

  it("counts int_uniform and q_uniform ranges", () => {
    const total = sweepTotalTrials({
      method: "grid",
      parameters: {
        layers: { min: 1, max: 4 },
        dropout: { distribution: "q_uniform", min: 0.1, max: 0.3, q: 0.1 },
      },
    });
    expect(total).toBe(12);
  });

  it("caps grid totals at run_cap", () => {
    const total = sweepTotalTrials({
      method: "grid",
      run_cap: 4,
      parameters: { lr: { values: [1, 2, 3, 4, 5, 6] } },
    });
    expect(total).toBe(4);
  });

  it("returns run_cap for non-grid methods", () => {
    expect(
      sweepTotalTrials({
        method: "random",
        run_cap: 20,
        parameters: { lr: { min: 0.001, max: 0.1 } },
      }),
    ).toBe(20);
    expect(
      sweepTotalTrials({
        method: "bayes",
        parameters: { lr: { min: 0.001, max: 0.1 } },
      }),
    ).toBeNull();
  });

  it("returns run_cap when a grid parameter is continuous", () => {
    expect(
      sweepTotalTrials({
        method: "grid",
        parameters: { lr: { min: 0.001, max: 0.1 } },
      }),
    ).toBeNull();
  });
});

describe("describeParamSpec", () => {
  it("describes values, constants, and ranges", () => {
    expect(describeParamSpec({ values: [0.1, "adam"] })).toBe('0.1, "adam"');
    expect(describeParamSpec({ value: 42 })).toBe("42");
    expect(describeParamSpec({ min: 0, max: 1 })).toBe("0 – 1");
    expect(
      describeParamSpec({ distribution: "log_uniform_values", min: 1e-4, max: 0.1 }),
    ).toBe("0.0001 – 0.1 (log_uniform_values)");
  });
});

describe("sweepParamSpecs", () => {
  it("returns path/description pairs", () => {
    const specs = sweepParamSpecs({
      parameters: { lr: { values: [0.1] }, nested: { parameters: { a: 1 } } },
    });
    expect(specs).toEqual([
      { path: "lr", description: "0.1" },
      { path: "nested.a", description: "1" },
    ]);
  });

  it("handles missing config", () => {
    expect(sweepParamSpecs(null)).toEqual([]);
  });
});

describe("trialParamKeys", () => {
  it("collects keys in first-seen order", () => {
    const keys = trialParamKeys([
      { params: { lr: 0.1, batch: 16 } },
      { params: { batch: 32, momentum: 0.9 } },
    ]);
    expect(keys).toEqual(["lr", "batch", "momentum"]);
  });
});
