import { parse, View } from "vega";
import { compile } from "vega-lite";
import { describe, expect, test } from "vitest";

import {
  BAR_LABEL_LIMIT,
  buildBarLabelLayout,
  maxBarLabelWidth,
  settleBarLabels,
} from "./barAxis.js";

function runNames(count) {
  return Array.from(
    { length: count },
    (_, i) => `coyotte508-${1793476124 + i * 14}`,
  );
}

async function renderChart(names, widths) {
  const values = names.map((name, i) => ({ key: `series-${i}`, label: name, value: i + 1 }));
  const labelLayout = buildBarLabelLayout(
    Object.fromEntries(values.map((d) => [d.key, d.label])),
  );
  const spec = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    width: "container",
    height: 250,
    autosize: { type: "fit", contains: "padding" },
    params: labelLayout.params,
    data: { values },
    mark: "bar",
    encoding: {
      x: {
        field: "key",
        type: "nominal",
        sort: values.map((d) => d.key),
        axis: labelLayout.axis,
        title: null,
      },
      y: { field: "value", type: "quantitative" },
    },
  };
  const view = new View(parse(compile(spec).spec), { renderer: "none" });
  await view.runAsync();
  for (const width of widths) {
    view.width(width);
    await view.resize().runAsync();
    await settleBarLabels(view);
  }
  const labels = [];
  const visit = (node) => {
    if (node.role === "axis-label") {
      for (const item of node.items) labels.push(item);
    }
    for (const item of node.items || []) {
      if (item.items) item.items.forEach(visit);
    }
  };
  visit(view.scenegraph().root);
  const plotHeight = view.height();
  view.finalize();
  return {
    labels: labels.filter((d) => d.text.startsWith("coyotte508")),
    plotHeight,
  };
}

function overlapping(labels) {
  const visible = labels.filter((d) => d.opacity !== 0);
  const pairs = [];
  for (let i = 1; i < visible.length; i++) {
    if (visible[i - 1].bounds.intersects(visible[i].bounds)) {
      pairs.push([visible[i - 1].text, visible[i].text]);
    }
  }
  return pairs;
}

function offTick(labels) {
  return labels
    .filter((d) => Math.abs((d.bounds.x1 + d.bounds.x2) / 2 - d.x) > 1)
    .map((d) => d.text);
}

describe("bar chart x-axis labels", () => {
  test("keeps labels horizontal and centered when every band fits its label", async () => {
    const { labels } = await renderChart(runNames(4), [900]);

    expect(labels.map((d) => d.angle)).toEqual([0, 0, 0, 0]);
    expect(labels.every((d) => d.opacity !== 0)).toBe(true);
    expect(offTick(labels)).toEqual([]);
    expect(overlapping(labels)).toEqual([]);
  });

  test("rotates labels that would collide in a narrow chart", async () => {
    const { labels } = await renderChart(runNames(4), [340]);

    expect(labels.every((d) => d.angle === -90)).toBe(true);
    expect(labels.every((d) => d.opacity !== 0)).toBe(true);
    expect(offTick(labels)).toEqual([]);
    expect(overlapping(labels)).toEqual([]);
  });

  test("hides labels rather than drawing them on top of each other", async () => {
    const { labels } = await renderChart(runNames(36), [340]);

    expect(labels).toHaveLength(36);
    expect(labels.some((d) => d.opacity === 0)).toBe(true);
    expect(labels.some((d) => d.opacity !== 0)).toBe(true);
    expect(overlapping(labels)).toEqual([]);
  });

  test("reserves room for vertical labels whichever way the chart is resized", async () => {
    const narrow = await renderChart(runNames(2), [294]);
    const wide = await renderChart(runNames(2), [900]);
    const narrowed = await renderChart(runNames(2), [900, 294]);
    const widened = await renderChart(runNames(2), [294, 900]);

    expect(narrow.labels.every((d) => d.angle === -90)).toBe(true);
    expect(narrow.plotHeight).toBeLessThan(wide.plotHeight - BAR_LABEL_LIMIT / 2);
    expect(narrowed.plotHeight).toBe(narrow.plotHeight);
    expect(widened.plotHeight).toBe(wide.plotHeight);
  });

  test("caps the measured width at the label limit", () => {
    expect(maxBarLabelWidth(["x".repeat(500)])).toBe(BAR_LABEL_LIMIT);
    expect(maxBarLabelWidth(["ab"])).toBeLessThan(BAR_LABEL_LIMIT);
  });
});
