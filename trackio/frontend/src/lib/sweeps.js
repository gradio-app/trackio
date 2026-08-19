export function flattenParameterSpecs(parameters, prefix = "") {
  const flat = {};
  for (const [name, rawSpec] of Object.entries(parameters || {})) {
    const spec =
      rawSpec && typeof rawSpec === "object" && !Array.isArray(rawSpec)
        ? rawSpec
        : { value: rawSpec };
    const path = `${prefix}${name}`;
    if (spec.parameters && typeof spec.parameters === "object") {
      Object.assign(flat, flattenParameterSpecs(spec.parameters, `${path}.`));
    } else {
      flat[path] = spec;
    }
  }
  return flat;
}

function inferDistribution(spec) {
  if (spec.distribution) return spec.distribution;
  if ("values" in spec) return "categorical";
  if ("value" in spec) return "constant";
  if ("min" in spec && "max" in spec) {
    return Number.isInteger(spec.min) && Number.isInteger(spec.max)
      ? "int_uniform"
      : "uniform";
  }
  return null;
}

function gridValueCount(spec) {
  const distribution = inferDistribution(spec);
  if (distribution === "constant") return 1;
  if (
    distribution === "categorical" ||
    distribution === "categorical_w_probabilities"
  ) {
    return Array.isArray(spec.values) ? spec.values.length : null;
  }
  if (distribution === "int_uniform") {
    if (!Number.isInteger(spec.min) || !Number.isInteger(spec.max)) return null;
    return spec.max - spec.min + 1;
  }
  if (distribution === "q_uniform") {
    const q = spec.q ?? 1.0;
    if (typeof spec.min !== "number" || typeof spec.max !== "number" || q <= 0)
      return null;
    const kLo = Math.ceil(spec.min / q - 1e-9);
    const kHi = Math.floor(spec.max / q + 1e-9);
    return kHi >= kLo ? kHi - kLo + 1 : null;
  }
  return null;
}

export function sweepTotalTrials(config) {
  if (!config || typeof config !== "object") return null;
  const runCap =
    Number.isInteger(config.run_cap) && config.run_cap > 0
      ? config.run_cap
      : null;
  if (config.method !== "grid") return runCap;
  const specs = Object.values(flattenParameterSpecs(config.parameters));
  if (specs.length === 0) return runCap;
  let total = 1;
  for (const spec of specs) {
    const count = gridValueCount(spec);
    if (count == null || !Number.isFinite(count) || count <= 0) return runCap;
    total *= count;
  }
  return runCap != null ? Math.min(total, runCap) : total;
}

export function describeParamSpec(spec) {
  if (spec == null || typeof spec !== "object" || Array.isArray(spec)) {
    return JSON.stringify(spec);
  }
  if ("value" in spec) return JSON.stringify(spec.value);
  if ("values" in spec && Array.isArray(spec.values)) {
    return spec.values.map((v) => JSON.stringify(v)).join(", ");
  }
  if ("min" in spec && "max" in spec) {
    const extras = [];
    if (spec.distribution) extras.push(spec.distribution);
    if (spec.q != null) extras.push(`q=${spec.q}`);
    const suffix = extras.length > 0 ? ` (${extras.join(", ")})` : "";
    return `${spec.min} – ${spec.max}${suffix}`;
  }
  if (spec.distribution) return spec.distribution;
  return JSON.stringify(spec);
}

export function sweepParamSpecs(config) {
  return Object.entries(flattenParameterSpecs(config?.parameters)).map(
    ([path, spec]) => ({ path, description: describeParamSpec(spec) }),
  );
}

export function trialParamKeys(trials) {
  const keys = [];
  const seen = new Set();
  for (const trial of trials || []) {
    for (const key of Object.keys(trial?.params || {})) {
      if (!seen.has(key)) {
        seen.add(key);
        keys.push(key);
      }
    }
  }
  return keys;
}
