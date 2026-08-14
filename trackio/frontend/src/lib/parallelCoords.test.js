import { describe, expect, test } from "vitest";
import { compile } from "vega-lite";
import { parse, View } from "vega";
import {
  buildParallelCoordsData,
  buildParallelCoordsSpec,
} from "./parallelCoords.js";

const trial = (id, params, metricValue, runId = null) => ({
  trial_id: id,
  params,
  metric_value: metricValue,
  run_id: runId,
});

describe("buildParallelCoordsData", () => {
  test("returns empty data when there are fewer than 2 usable trials", () => {
    expect(buildParallelCoordsData([], "loss")).toEqual({ axes: [], rows: [] });
    expect(buildParallelCoordsData(null, "loss")).toEqual({
      axes: [],
      rows: [],
    });
    expect(
      buildParallelCoordsData([trial(1, { lr: 0.1 }, 0.5)], "loss"),
    ).toEqual({ axes: [], rows: [] });
  });

  test("excludes trials without a metric value or params", () => {
    const { axes, rows } = buildParallelCoordsData(
      [
        trial(1, { lr: 0.1 }, 0.5),
        trial(2, { lr: 0.01 }, 0.2),
        trial(3, { lr: 0.001 }, null),
        trial(4, {}, 0.9),
      ],
      "loss",
    );
    expect(axes.map((a) => a.key)).toEqual(["lr", "loss"]);
    const trialIds = [...new Set(rows.map((r) => r.trial))];
    expect(trialIds).toEqual([1, 2]);
  });

  test("normalizes numeric params to [0, 1]", () => {
    const { rows } = buildParallelCoordsData(
      [
        trial(1, { lr: 0.1 }, 1.0),
        trial(2, { lr: 0.2 }, 3.0),
        trial(3, { lr: 0.3 }, 2.0),
      ],
      "loss",
    );
    const lrPositions = rows
      .filter((r) => r.axis === "lr")
      .map((r) => r.position);
    expect(lrPositions[0]).toBeCloseTo(0);
    expect(lrPositions[1]).toBeCloseTo(0.5);
    expect(lrPositions[2]).toBeCloseTo(1);
    const metricPositions = rows
      .filter((r) => r.axis === "loss")
      .map((r) => r.position);
    expect(metricPositions).toEqual([0, 1, 0.5]);
  });

  test("places constant numeric params at the axis midpoint", () => {
    const { axes, rows } = buildParallelCoordsData(
      [trial(1, { epochs: 5 }, 0.1), trial(2, { epochs: 5 }, 0.2)],
      "loss",
    );
    const epochsAxis = axes.find((a) => a.key === "epochs");
    expect(epochsAxis.ticks).toEqual([{ position: 0.5, label: "5" }]);
    for (const row of rows.filter((r) => r.axis === "epochs")) {
      expect(row.position).toBe(0.5);
    }
  });

  test("maps categorical params to evenly spaced sorted positions", () => {
    const { axes, rows } = buildParallelCoordsData(
      [
        trial(1, { opt: "sgd" }, 0.1),
        trial(2, { opt: "adam" }, 0.2),
        trial(3, { opt: "rmsprop" }, 0.3),
      ],
      "loss",
    );
    const optAxis = axes.find((a) => a.key === "opt");
    expect(optAxis.kind).toBe("categorical");
    expect(optAxis.categories).toEqual(["adam", "rmsprop", "sgd"]);
    const positions = Object.fromEntries(
      rows.filter((r) => r.axis === "opt").map((r) => [r.value, r.position]),
    );
    expect(positions).toEqual({ adam: 0, rmsprop: 0.5, sgd: 1 });
  });

  test("treats mixed-type params as categorical", () => {
    const { axes } = buildParallelCoordsData(
      [trial(1, { batch: 32 }, 0.1), trial(2, { batch: "auto" }, 0.2)],
      "loss",
    );
    expect(axes.find((a) => a.key === "batch").kind).toBe("categorical");
  });

  test("skips a missing param for a trial without dropping the trial", () => {
    const { rows } = buildParallelCoordsData(
      [
        trial(1, { lr: 0.1, momentum: 0.9 }, 0.5),
        trial(2, { lr: 0.2 }, 0.3),
      ],
      "loss",
    );
    const trial2Axes = rows.filter((r) => r.trial === 2).map((r) => r.axis);
    expect(trial2Axes).toEqual(["lr", "loss"]);
  });

  test("appends the metric as the final axis with min/max ticks", () => {
    const { axes } = buildParallelCoordsData(
      [trial(1, { lr: 0.1 }, 0.25), trial(2, { lr: 0.2 }, 0.75)],
      "val/accuracy",
    );
    const last = axes[axes.length - 1];
    expect(last.key).toBe("val/accuracy");
    expect(last.ticks).toEqual([
      { position: 0, label: "0.25" },
      { position: 1, label: "0.75" },
    ]);
  });

  test("spec compiles and renders to SVG", async () => {
    const plotData = buildParallelCoordsData(
      [
        trial(1, { lr: 0.1, opt: "adam", epochs: 5 }, 0.42, "run-a"),
        trial(2, { lr: 0.01, opt: "sgd", epochs: 5 }, 0.31, "run-b"),
        trial(3, { lr: 0.001, opt: "adam", epochs: 10 }, 0.55, "run-c"),
      ],
      "loss",
      "run-b",
    );
    const spec = {
      ...buildParallelCoordsSpec(plotData, {
        metricName: "loss",
        metricGoal: "minimize",
      }),
      width: 600,
    };
    const compiled = compile(spec).spec;
    const view = new View(parse(compiled), { renderer: "none" });
    const svg = await view.toSVG();
    view.finalize();
    expect(svg).toContain("<svg");
    expect(svg).toContain("loss");
  });

  test("marks rows from the best run", () => {
    const { rows } = buildParallelCoordsData(
      [
        trial(1, { lr: 0.1 }, 0.5, "run-a"),
        trial(2, { lr: 0.2 }, 0.2, "run-b"),
      ],
      "loss",
      "run-b",
    );
    expect(rows.filter((r) => r.best).every((r) => r.trial === 2)).toBe(true);
    expect(rows.some((r) => r.best)).toBe(true);
  });
});
