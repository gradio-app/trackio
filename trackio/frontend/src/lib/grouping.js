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

export function resolveGroupByKey(displayLabel, runConfigs) {
  if (!displayLabel) return null;
  for (const [key, label] of Object.entries(PROMOTED_RESERVED_KEYS)) {
    if (label === displayLabel && promotedKeyHasVariance(runConfigs, key)) return key;
  }
  return displayLabel;
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
    .map(displayLabelForKey);
  const surfacedPromotedLabels = new Set(promoted);

  const regularKeys = new Set();
  for (const cfg of Object.values(runConfigs ?? {})) {
    if (!cfg || typeof cfg !== "object") continue;
    for (const key of Object.keys(cfg)) {
      if (cfg[key] === null || cfg[key] === undefined) continue;
      if (shouldHideKey(key)) continue;
      if (key in PROMOTED_RESERVED_KEYS) continue;
      if (surfacedPromotedLabels.has(key)) continue;
      regularKeys.add(key);
    }
  }
  const regular = [...regularKeys].sort();
  return ["None", ...promoted, ...regular];
}

export function computeGroupedRuns(filteredRuns, runConfigs, groupBy) {
  const realKey = resolveGroupByKey(groupBy, runConfigs);
  if (!realKey) return null;
  const groups = new Map();
  for (const run of filteredRuns) {
    const cfg = (runConfigs ?? {})[run.id] ?? (runConfigs ?? {})[run.name] ?? {};
    const raw = cfg[realKey];
    const label = raw === null || raw === undefined ? "(unset)" : String(raw);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(run);
  }
  return groups;
}
