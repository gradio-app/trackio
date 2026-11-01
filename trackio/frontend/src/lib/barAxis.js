import { textMetrics } from "vega";

export const BAR_LABEL_LIMIT = 120;
export const BAR_LABEL_FONT = { font: "sans-serif", fontSize: 10 };
const BAR_LABEL_GAP = 4;

export function maxBarLabelWidth(labels) {
  let widest = 0;
  for (const label of labels) {
    const width = textMetrics.width(BAR_LABEL_FONT, String(label ?? ""));
    if (width > widest) widest = width;
  }
  return Math.min(BAR_LABEL_LIMIT, Math.ceil(widest));
}

export function buildBarXAxis(labelByKey) {
  const needed = maxBarLabelWidth(Object.values(labelByKey)) + BAR_LABEL_GAP;
  return {
    labelAngle: { expr: `bandwidth('x') >= ${needed} ? 0 : -90` },
    labelLimit: BAR_LABEL_LIMIT,
    labelFont: BAR_LABEL_FONT.font,
    labelFontSize: BAR_LABEL_FONT.fontSize,
    labelOverlap: "greedy",
    labelSeparation: 2,
    labelExpr: `${JSON.stringify(labelByKey)}[datum.value] || datum.value`,
  };
}
