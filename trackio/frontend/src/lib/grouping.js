export const PROMOTED_RESERVED_KEYS = Object.freeze({
  _Group: "Group",
  _Username: "Username",
});

function shouldHideKey(key) {
  return key.startsWith("_") && !(key in PROMOTED_RESERVED_KEYS);
}

function displayLabelForKey(key) {
  return PROMOTED_RESERVED_KEYS[key] ?? key;
}

function promotedKeyHasVariance(runConfigs, key) {
  const seen = new Set();
  for (const cfg of Object.values(runConfigs ?? {})) {
    if (!cfg || typeof cfg !== "object") continue;
    const raw = cfg[key];
    const label = raw === null || raw === undefined ? "(unset)" : String(raw);
    seen.add(label);
    if (seen.size >= 2) return true;
  }
  return false;
}

export function computeGroupByOptions(runConfigs) {
  const promoted = Object.keys(PROMOTED_RESERVED_KEYS)
    .filter((k) => promotedKeyHasVariance(runConfigs, k))
    .map((k) => ({ label: displayLabelForKey(k), value: k }));
  const surfacedPromotedLabels = new Set(promoted.map((o) => o.label));

  const regularKeys = new Set();
  for (const cfg of Object.values(runConfigs ?? {})) {
    if (!cfg || typeof cfg !== "object") continue;
    for (const key of Object.keys(cfg)) {
      if (cfg[key] === null || cfg[key] === undefined) continue;
      if (typeof cfg[key] === "object") continue;
      if (shouldHideKey(key)) continue;
      if (key in PROMOTED_RESERVED_KEYS) continue;
      if (surfacedPromotedLabels.has(key)) continue;
      regularKeys.add(key);
    }
  }
  const regular = [...regularKeys].sort().map((k) => ({ label: k, value: k }));
  return [{ label: "None", value: null }, ...promoted, ...regular];
}

export function computeGroupedRuns(filteredRuns, runConfigs, groupBy) {
  if (!groupBy) return null;
  const groups = new Map();
  for (const run of filteredRuns) {
    const cfg = (runConfigs ?? {})[run.id] ?? (runConfigs ?? {})[run.name] ?? {};
    const raw = cfg[groupBy];
    const label = raw === null || raw === undefined ? "(unset)" : String(raw);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(run);
  }
  return groups;
}
