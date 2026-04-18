export function visibleLegendEntries(entries, expanded, threshold) {
  if (!entries || entries.length === 0) return [];
  if (expanded || entries.length <= threshold) return entries;
  return entries.slice(0, threshold);
}
