function finiteOrZero(value) {
  return Number.isFinite(value) ? value : 0;
}

function compareByStep(a, b) {
  return (
    finiteOrZero(a.step) - finiteOrZero(b.step) ||
    finiteOrZero(a._index) - finiteOrZero(b._index)
  );
}

/**
 * Groups media items that share a run and key so each group can be shown as
 * one card with a step slider. Groups keep the order of their first item in
 * `items`; items within a group are ordered by ascending step.
 */
export function groupMediaByKey(items) {
  const groups = new Map();
  for (const item of items) {
    const id = `${item._runId ?? item._run}\u0000${item.key}`;
    if (!groups.has(id)) groups.set(id, { id, items: [] });
    groups.get(id).items.push(item);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    items: group.items.sort(compareByStep),
  }));
}
