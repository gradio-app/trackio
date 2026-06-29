import { describe, expect, test } from "vitest";
import { computeMetricPlotData, processRunData } from "./dataProcessing.js";

describe("processRunData smoothing", () => {
  test("does not fabricate values for rows that did not log the metric", () => {
    const logs = [
      { step: 0, "train/loss": 1.0 },
      { step: 0, "train/loss": 1.1 },
      { step: 0, "train/loss": 0.9 },
      { step: 0, epoch: 0, "train/avg_loss": 1.0 },
      { step: 1, "train/loss": 0.8 },
      { step: 1, "train/loss": 0.7 },
      { step: 1, "train/loss": 0.75 },
      { step: 1, epoch: 1, "train/avg_loss": 0.75 },
    ];

    const { rows } = processRunData(logs, "run-1", 10, "step", false, false);

    const epochSmoothed = rows.filter(
      (r) => r.data_type === "smoothed" && r.epoch != null,
    );
    expect(epochSmoothed.length).toBe(2);
    expect(epochSmoothed.map((r) => r.step).sort()).toEqual([0, 1]);
  });

  test("computeMetricPlotData returns one point per logged epoch", () => {
    const logs = [
      { step: 0, "train/loss": 1.0 },
      { step: 0, "train/loss": 1.1 },
      { step: 0, epoch: 0 },
      { step: 1, "train/loss": 0.8 },
      { step: 1, "train/loss": 0.7 },
      { step: 1, epoch: 1 },
      { step: 2, "train/loss": 0.6 },
      { step: 2, epoch: 2 },
    ];
    const { rows } = processRunData(logs, "run-1", 10, "step", false, false);
    const { data } = computeMetricPlotData(rows, "step", "epoch", null);
    const originals = data.filter((r) => r.data_type === "original");
    const smoothed = data.filter((r) => r.data_type === "smoothed");
    expect(originals.length).toBe(3);
    expect(smoothed.length).toBe(3);
  });

  test("dense metrics are still smoothed across all rows", () => {
    const logs = [
      { step: 0, loss: 1.0 },
      { step: 1, loss: 0.9 },
      { step: 2, loss: 0.8 },
      { step: 3, loss: 0.7 },
      { step: 4, loss: 0.6 },
    ];
    const { rows } = processRunData(logs, "run-1", 3, "step", false, false);
    const smoothed = rows.filter((r) => r.data_type === "smoothed");
    expect(smoothed.length).toBe(5);
    expect(smoothed.every((r) => typeof r.loss === "number")).toBe(true);
  });

  test("falls back to step when a requested custom x-axis is unavailable", () => {
    const logs = [
      { step: 0, loss: 1.0 },
      { step: 1, loss: 0.9 },
    ];

    const result = processRunData(
      logs,
      "run-1",
      0,
      "missing_axis",
      false,
      false,
    );

    expect(result.xColumn).toBe("step");
  });
});
