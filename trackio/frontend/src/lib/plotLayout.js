/**
 * Column resolution for the metrics plot grid.
 *
 * The grid runs in one of two modes: "auto", where CSS picks the column count
 * from the available width, and a fixed count chosen by the user.
 */

export const AUTO_PANELS_PER_ROW = "auto";

export const PANELS_PER_ROW_CHOICES = [
  { label: "Auto", value: AUTO_PANELS_PER_ROW },
  1, 2, 3, 4, 5, 6,
];

export function isAutoPanels(panelsPerRow) {
  return panelsPerRow === AUTO_PANELS_PER_ROW;
}

export function parsePlotsPerRow(value) {
  if (value === AUTO_PANELS_PER_ROW) return AUTO_PANELS_PER_ROW;
  const count = Number(value);
  return Number.isInteger(count) && PANELS_PER_ROW_CHOICES.includes(count)
    ? count
    : null;
}

export function getPlotColumns(panelsPerRow, itemCount) {
  const count = Math.max(1, Math.floor(itemCount) || 1);
  if (isAutoPanels(panelsPerRow)) return count;
  const limit = Math.floor(Number(panelsPerRow));
  if (!Number.isFinite(limit) || limit < 1) return count;
  return Math.min(limit, count);
}
