export function latestOnlySelection(filteredRunIds) {
  if (!filteredRunIds || filteredRunIds.length === 0) return [];
  return [filteredRunIds[0]];
}

export function reconcileSelectedRuns(prevSelected, newOrderedIds, prevOrderedIds) {
  const prev = prevSelected ?? [];
  const ordered = newOrderedIds ?? [];
  const prevOrdered = prevOrderedIds ?? [];
  const newIdSet = new Set(ordered);
  const kept = prev.filter((r) => newIdSet.has(r));

  if (prev.length === 0 || kept.length === 0) {
    return [...ordered];
  }

  const allPrevSelected =
    prevOrdered.length > 0 && prev.length === prevOrdered.length;
  if (allPrevSelected) {
    const keptSet = new Set(kept);
    const additions = ordered.filter((r) => !keptSet.has(r));
    return [...kept, ...additions];
  }

  return kept;
}
