import { filterMetricsByRegex } from "./dataProcessing.js";

export function configKeyLabel(key) {
  return JSON.parse(key).map((part, i) => /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(part)
    ? `${i ? "." : ""}${part}` : `[${JSON.stringify(part)}]`).join("");
}

export function parseConfigFilters(value) {
  try {
    const groups = JSON.parse(value);
    if (!Array.isArray(groups) || !groups.every((group) => Array.isArray(group) && group.every((rule) => {
      if (!rule || typeof rule.key !== "string" || typeof rule.value !== "string") return false;
      const path = JSON.parse(rule.key);
      return Array.isArray(path) && path.length > 0 && path.every((key) => typeof key === "string")
        && ["=", "!=", ">", ">=", "<", "<=", "contains"].includes(rule.operator);
    }))) return [];
    return groups;
  } catch {
    return [];
  }
}

export function filterRunsByName(runs, pattern) {
  if (!pattern.trim()) return runs;
  const names = new Set(filterMetricsByRegex(runs.map((run) => run.name), pattern));
  return runs.filter((run) => names.has(run.name));
}

export function configFilterKeys(configs) {
  const keys = new Set();
  function visit(value, path = []) {
    for (const [key, child] of Object.entries(value ?? {})) {
      if (!path.length && key.startsWith("_")) continue;
      const next = [...path, key];
      if (child !== null && typeof child === "object") {
        if (!Array.isArray(child)) visit(child, next);
      } else {
        keys.add(JSON.stringify(next));
      }
    }
  }
  for (const config of Object.values(configs)) visit(config);
  return [...keys].map((value) => ({ value, label: configKeyLabel(value) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function compileConfigFilter(groups) {
  const compiled = groups.map((group) => group.filter((rule) => rule.key).map((rule) => {
    const path = JSON.parse(rule.key);
    const expected = rule.value.trim();
    return (config) => {
      let actual = config;
      for (const key of path) {
        if (actual == null || !Object.hasOwn(actual, key)) return false;
        actual = actual[key];
      }
      if (actual !== null && typeof actual === "object") return false;
      const equal = typeof actual === "number"
        ? expected !== "" && actual === Number(expected)
        : String(actual) === rule.value;
      switch (rule.operator) {
        case "=": return equal;
        case "!=": return !equal;
        case "contains": return typeof actual === "string" && actual.includes(rule.value);
        case ">": return typeof actual === "number" && expected !== "" && actual > Number(expected);
        case ">=": return typeof actual === "number" && expected !== "" && actual >= Number(expected);
        case "<": return typeof actual === "number" && expected !== "" && actual < Number(expected);
        case "<=": return typeof actual === "number" && expected !== "" && actual <= Number(expected);
        default: return false;
      }
    };
  })).filter((group) => group.length);
  return (config) => !compiled.length || compiled.some((group) => group.every((match) => match(config)));
}

export function filterRunsByConfig(runs, configs, match) {
  return runs.filter((run) => match(configs[run.id] ?? configs[run.name] ?? {}));
}
