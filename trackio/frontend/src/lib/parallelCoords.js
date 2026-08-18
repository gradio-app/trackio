import { formatCompactNumber } from "./format.js";

export const METRIC_COLOR_RANGE_LIGHT = ["#93c5fd", "#1e3a8a"];
export const METRIC_COLOR_RANGE_DARK = ["#2563eb", "#bfdbfe"];

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function formatTickValue(value) {
  if (isFiniteNumber(value)) return formatCompactNumber(value);
  return String(value);
}

function normalizeNumeric(value, min, max) {
  if (max === min) return 0.5;
  return (value - min) / (max - min);
}

function numericAxis(key, min, max) {
  return {
    key,
    kind: "numeric",
    min,
    max,
    ticks:
      min === max
        ? [{ position: 0.5, label: formatTickValue(min) }]
        : [
            { position: 0, label: formatTickValue(min) },
            { position: 1, label: formatTickValue(max) },
          ],
  };
}

function categoryPosition(categories, index) {
  return categories.length === 1 ? 0.5 : index / (categories.length - 1);
}

export function buildParallelCoordsData(
  trials,
  metricName,
  bestRunId = null,
) {
  const usable = (trials || []).filter(
    (trial) =>
      trial &&
      trial.metric_value != null &&
      isFiniteNumber(Number(trial.metric_value)) &&
      trial.params &&
      Object.keys(trial.params).length > 0,
  );
  if (usable.length < 2) return { axes: [], rows: [] };

  const paramKeys = [];
  const seen = new Set();
  for (const trial of usable) {
    for (const key of Object.keys(trial.params)) {
      if (!seen.has(key)) {
        seen.add(key);
        paramKeys.push(key);
      }
    }
  }

  const axes = [];
  for (const key of paramKeys) {
    const values = usable
      .map((trial) => trial.params[key])
      .filter((value) => value !== null && value !== undefined);
    if (values.length === 0) continue;
    const allNumeric = values.every((value) => isFiniteNumber(value));
    if (allNumeric) {
      axes.push(numericAxis(key, Math.min(...values), Math.max(...values)));
    } else {
      const categories = [...new Set(values.map((value) => String(value)))];
      categories.sort();
      axes.push({
        key,
        kind: "categorical",
        categories,
        ticks: categories.map((category, i) => ({
          position: categoryPosition(categories, i),
          label: category,
        })),
      });
    }
  }

  const metricValues = usable.map((trial) => Number(trial.metric_value));
  const metricMin = Math.min(...metricValues);
  const metricMax = Math.max(...metricValues);
  let metricKey = metricName || "metric";
  if (seen.has(metricKey)) metricKey = `${metricKey} (metric)`;
  const metricAxis = numericAxis(metricKey, metricMin, metricMax);
  axes.push(metricAxis);

  const rows = [];
  for (const trial of usable) {
    const metricValue = Number(trial.metric_value);
    const best = bestRunId != null && trial.run_id === bestRunId;
    for (const axis of axes) {
      let raw;
      let position;
      if (axis === metricAxis) {
        raw = metricValue;
        position = normalizeNumeric(metricValue, axis.min, axis.max);
      } else {
        raw = trial.params[axis.key];
        if (raw === null || raw === undefined) continue;
        if (axis.kind === "numeric") {
          position = normalizeNumeric(raw, axis.min, axis.max);
        } else {
          const index = axis.categories.indexOf(String(raw));
          position = categoryPosition(axis.categories, index);
        }
      }
      rows.push({
        trial: trial.trial_id,
        axis: axis.key,
        position,
        value: formatTickValue(raw),
        metric: metricValue,
        best,
      });
    }
  }

  return { axes, rows };
}

export function buildParallelCoordsSpec(
  { axes, rows },
  {
    metricName = "",
    metricGoal = "minimize",
    gridColor = "#e5e7eb",
    labelColor = "#6b7280",
    titleColor = "#374151",
    metricColorRange = METRIC_COLOR_RANGE_LIGHT,
  } = {},
) {
  const axisOrder = axes.map((a) => a.key);
  const lastAxisKey = axisOrder[axisOrder.length - 1];
  const ticks = axes.flatMap((axis) =>
    axis.ticks.map((t) => ({
      axis: axis.key,
      position: t.position,
      label: t.label,
    })),
  );
  const leftTicks = ticks.filter((t) => t.axis === lastAxisKey);
  const rightTicks = ticks.filter((t) => t.axis !== lastAxisKey);

  const xEncoding = {
    field: "axis",
    type: "nominal",
    sort: axisOrder,
    scale: { type: "point", padding: 0.06 },
    axis: {
      title: null,
      orient: "top",
      labelAngle: 0,
      labelColor: titleColor,
      labelFontWeight: 600,
      labelPadding: 10,
      labelLimit: 110,
      domain: false,
      ticks: false,
      grid: false,
    },
  };
  const yEncoding = {
    field: "position",
    type: "quantitative",
    scale: { domain: [0, 1] },
    axis: null,
  };
  const tickTextMark = {
    type: "text",
    fontSize: 10,
    color: labelColor,
  };
  const tickTextEncoding = {
    x: xEncoding,
    y: yEncoding,
    text: { field: "label", type: "nominal" },
  };

  return {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height: 300,
    autosize: { type: "fit", contains: "padding" },
    padding: { top: 4, bottom: 12, left: 8, right: 8 },
    layer: [
      {
        data: { values: axes.map((a) => ({ axis: a.key })) },
        mark: { type: "rule", stroke: gridColor, strokeWidth: 1.5 },
        encoding: {
          x: xEncoding,
          y: { datum: 0, axis: null },
          y2: { datum: 1 },
        },
      },
      {
        data: { values: rightTicks },
        mark: { ...tickTextMark, align: "left", dx: 6 },
        encoding: tickTextEncoding,
      },
      {
        data: { values: leftTicks },
        mark: { ...tickTextMark, align: "right", dx: -6 },
        encoding: tickTextEncoding,
      },
      {
        data: { values: rows },
        params: [
          {
            name: "hoverTrial",
            select: {
              type: "point",
              fields: ["trial"],
              on: "pointerover",
              clear: "pointerout",
            },
          },
        ],
        mark: {
          type: "line",
          interpolate: "linear",
          point: { size: 30, filled: true },
        },
        encoding: {
          x: xEncoding,
          y: yEncoding,
          detail: { field: "trial", type: "nominal" },
          color: {
            field: "metric",
            type: "quantitative",
            title: metricName || "metric",
            scale: {
              range: metricColorRange,
              reverse: metricGoal === "minimize",
            },
            legend: null,
          },
          strokeWidth: {
            condition: { test: "datum.best", value: 3 },
            value: 1.5,
          },
          opacity: {
            condition: { param: "hoverTrial", empty: false, value: 1 },
            value: 0.65,
          },
          tooltip: [
            { field: "trial", type: "nominal", title: "Trial" },
            { field: "axis", type: "nominal", title: "Axis" },
            { field: "value", type: "nominal", title: "Value" },
            {
              field: "metric",
              type: "quantitative",
              title: metricName || "metric",
            },
          ],
        },
      },
    ],
    config: {
      background: "transparent",
      view: { stroke: "transparent" },
    },
  };
}
