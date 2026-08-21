export function buildOptimizationHistoryData(
  trials,
  metricGoal = "minimize",
  bestRunId = null,
) {
  const usable = (trials || []).filter(
    (trial) =>
      trial &&
      trial.metric_value != null &&
      Number.isFinite(Number(trial.metric_value)),
  );
  if (usable.length < 2) return { points: [] };
  const sorted = [...usable].sort((a, b) => a.trial_id - b.trial_id);
  const better =
    metricGoal === "maximize" ? (a, b) => a > b : (a, b) => a < b;
  let runningBest = null;
  const points = sorted.map((trial) => {
    const metric = Number(trial.metric_value);
    if (runningBest == null || better(metric, runningBest)) {
      runningBest = metric;
    }
    return {
      trial: trial.trial_id,
      metric,
      runningBest,
      best: bestRunId != null && trial.run_id === bestRunId,
    };
  });
  return { points };
}

export function buildOptimizationHistorySpec(
  { points },
  {
    metricName = "",
    gridColor = "#e5e7eb",
    labelColor = "#6b7280",
    titleColor = "#374151",
    pointColor = "#2563eb",
    bestColor = "#d97706",
    lineColor = "#9ca3af",
  } = {},
) {
  const xEncoding = {
    field: "trial",
    type: "quantitative",
    title: "trial",
    scale: { nice: false, zero: false, padding: 12 },
    axis: { tickMinStep: 1, format: "d", grid: false },
  };
  const metricTitle = metricName || "metric";
  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height: "container",
    autosize: { type: "fit", contains: "padding" },
    padding: { top: 8, bottom: 4, left: 4, right: 8 },
    layer: [
      {
        data: { values: points },
        mark: {
          type: "line",
          interpolate: "step-after",
          color: lineColor,
          strokeWidth: 1.5,
          strokeDash: [4, 3],
        },
        encoding: {
          x: xEncoding,
          y: {
            field: "runningBest",
            type: "quantitative",
            title: metricTitle,
            scale: { zero: false },
          },
        },
      },
      {
        data: { values: points },
        mark: { type: "point", filled: true, opacity: 0.9 },
        encoding: {
          x: xEncoding,
          y: {
            field: "metric",
            type: "quantitative",
            title: metricTitle,
            scale: { zero: false },
          },
          color: {
            condition: { test: "datum.best", value: bestColor },
            value: pointColor,
          },
          size: {
            condition: { test: "datum.best", value: 130 },
            value: 55,
          },
          tooltip: [
            { field: "trial", type: "quantitative", title: "Trial" },
            { field: "metric", type: "quantitative", title: metricTitle },
            {
              field: "runningBest",
              type: "quantitative",
              title: "Best so far",
            },
          ],
        },
      },
    ],
    config: {
      background: "transparent",
      view: { stroke: "transparent" },
      axis: {
        gridColor,
        labelColor,
        titleColor,
        domainColor: gridColor,
        tickColor: gridColor,
      },
    },
  };
}
