export const VEGA_LITE_SCHEMA =
  "https://vega.github.io/schema/vega-lite/v6.json";

export function buildAxisLabelExpression(labelByKey) {
  const labelLookup = JSON.stringify(labelByKey)
    .replaceAll("<", "\\u003c")
    .replaceAll(">", "\\u003e")
    .replaceAll("&", "\\u0026")
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
  return `${labelLookup}[datum.value] || datum.value`;
}
