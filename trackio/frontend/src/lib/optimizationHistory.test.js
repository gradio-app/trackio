import { describe, expect, it } from "vitest";
import {
  buildOptimizationHistoryData,
  buildOptimizationHistorySpec,
} from "./optimizationHistory.js";

const trials = [
  { trial_id: 2, metric_value: 0.5, run_id: "b", state: "finished" },
  { trial_id: 1, metric_value: 0.8, run_id: "a", state: "finished" },
  { trial_id: 3, metric_value: 0.6, run_id: "c", state: "finished" },
  { trial_id: 4, metric_value: null, run_id: "d", state: "running" },
];

describe("buildOptimizationHistoryData", () => {
  it("orders points by trial and tracks the running best (minimize)", () => {
    const { points } = buildOptimizationHistoryData(trials, "minimize", "b");
    expect(points.map((p) => p.trial)).toEqual([1, 2, 3]);
    expect(points.map((p) => p.runningBest)).toEqual([0.8, 0.5, 0.5]);
    expect(points.map((p) => p.best)).toEqual([false, true, false]);
  });

  it("tracks the running best when maximizing", () => {
    const { points } = buildOptimizationHistoryData(trials, "maximize", null);
    expect(points.map((p) => p.runningBest)).toEqual([0.8, 0.8, 0.8]);
  });

  it("requires at least two usable trials", () => {
    expect(
      buildOptimizationHistoryData([trials[0]], "minimize", null).points,
    ).toEqual([]);
    expect(buildOptimizationHistoryData([], "minimize", null).points).toEqual(
      [],
    );
  });
});

describe("buildOptimizationHistorySpec", () => {
  it("produces a two-layer spec with the metric name as title", () => {
    const data = buildOptimizationHistoryData(trials, "minimize", null);
    const spec = buildOptimizationHistorySpec(data, { metricName: "loss" });
    expect(spec.layer).toHaveLength(2);
    expect(spec.layer[0].encoding.y.field).toBe("runningBest");
    expect(spec.layer[1].encoding.y.title).toBe("loss");
  });
});
