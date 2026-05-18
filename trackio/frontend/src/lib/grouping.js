export const PROMOTED_RESERVED_KEYS = Object.freeze({ _Group: "Group" });

const PROMOTED_LABELS = new Set(Object.values(PROMOTED_RESERVED_KEYS));

function shouldHideKey(key) {
  return key.startsWith("_") && !(key in PROMOTED_RESERVED_KEYS);
}

function displayLabelForKey(key) {
  return PROMOTED_RESERVED_KEYS[key] ?? key;
}

export function resolveGroupByKey(displayLabel) {
  if (!displayLabel) return null;
  for (const [key, label] of Object.entries(PROMOTED_RESERVED_KEYS)) {
    if (label === displayLabel) return key;
  }
  return displayLabel;
}

export function computeGroupByOptions(runConfigs) {
  const promotedFound = new Set();
  const regularKeys = new Set();
  for (const cfg of Object.values(runConfigs ?? {})) {
    if (!cfg || typeof cfg !== "object") continue;
    for (const key of Object.keys(cfg)) {
      if (cfg[key] === null || cfg[key] === undefined) continue;
      if (shouldHideKey(key)) continue;
      if (key in PROMOTED_RESERVED_KEYS) {
        promotedFound.add(key);
      } else if (!PROMOTED_LABELS.has(key)) {
        regularKeys.add(key);
      }
    }
  }
  const promoted = Object.keys(PROMOTED_RESERVED_KEYS)
    .filter((k) => promotedFound.has(k))
    .map(displayLabelForKey);
  const regular = [...regularKeys].sort();
  return ["None", ...promoted, ...regular];
}

export function computeGroupedRuns(filteredRuns, runConfigs, groupBy) {
  const realKey = resolveGroupByKey(groupBy);
  if (!realKey) return null;
  const groups = new Map();
  for (const run of filteredRuns) {
    const cfg = (runConfigs ?? {})[run.name] ?? {};
    const raw = cfg[realKey];
    const label = raw === null || raw === undefined ? "(unset)" : String(raw);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(run);
  }
  return groups;
}
