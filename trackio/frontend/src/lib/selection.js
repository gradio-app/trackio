export function latestOnlySelection(filteredRunIds) {
  if (!filteredRunIds || filteredRunIds.length === 0) return [];
  return [filteredRunIds[0]];
}

export function reconcileSelectedRuns(prevSelected, newOrderedIds) {
  const prev = prevSelected ?? [];
  const ordered = newOrderedIds ?? [];
  const newIdSet = new Set(ordered);
  const kept = prev.filter((r) => newIdSet.has(r));

  if (kept.length === 0 && prev.length === 0) {
    return [...ordered];
  }

  const prevSet = new Set(prev);
  const additions = ordered.filter((r) => !prevSet.has(r));
  return [...kept, ...additions];
}
