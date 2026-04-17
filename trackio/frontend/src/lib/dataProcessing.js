const RESERVED_KEYS = [
  "project",
  "run",
  "timestamp",
  "step",
  "time",
  "metrics",
];

export function processRunData(
  logs,
  run,
  smoothingGranularity,
  xAxis,
  logScaleX,
  logScaleY,
) {
  if (!logs || logs.length === 0) return null;

  let rows = logs.map((row) => ({ ...row }));

  if (!Object.hasOwn(rows[0], "step")) {
    rows.forEach((r, i) => (r.step = i));
  }

  let xColumn = "step";
  if (xAxis === "time" && Object.hasOwn(rows[0], "timestamp")) {
    const firstTs = new Date(rows[0].timestamp).getTime();
    rows.forEach((r) => {
      r.time = (new Date(r.timestamp).getTime() - firstTs) / 1000;
    });
    xColumn = "time";
  } else if (xAxis !== "step") {
    xColumn = xAxis;
  }

  if (logScaleX) {
    rows.forEach((r) => {
      if (r[xColumn] != null) {
        const v = r[xColumn];
        r[xColumn] = v <= 0 ? Math.log10(Math.max(v, 0) + 1) : Math.log10(v);
      }
    });
  }

  const numericCols = getNumericColumns(rows);
  const yCols = numericCols.filter(
    (c) => !RESERVED_KEYS.includes(c) && c !== xColumn,
  );

  if (logScaleY) {
    rows.forEach((r) => {
      yCols.forEach((col) => {
        if (r[col] != null && typeof r[col] === "number") {
          const v = r[col];
          r[col] = v <= 0 ? Math.log10(Math.max(v, 0) + 1) : Math.log10(v);
        }
      });
    });
  }

  const runId = typeof run === "string" ? run : (run?.id ?? run?.name);
  const runName = typeof run === "string" ? run : (run?.name ?? run?.id);

  if (smoothingGranularity > 0) {
    const originals = rows.map((r) => ({
      ...r,
      run: runName,
      run_id: runId,
      series_key: runId,
      data_type: "original",
    }));
    const smoothed = smoothData(rows, yCols, smoothingGranularity).map(
      (r) => ({
        ...r,
        run: runName,
        run_id: runId,
        series_key: runId,
        data_type: "smoothed",
      }),
    );
    return { rows: [...originals, ...smoothed], xColumn };
  }

  return {
    rows: rows.map((r) => ({
      ...r,
      run: runName,
      run_id: runId,
      series_key: runId,
      data_type: "original",
    })),
    xColumn,
  };
}

function smoothData(rows, cols, windowSize) {
  const w = Math.max(3, Math.min(windowSize, rows.length));
  const half = Math.floor(w / 2);
  return rows.map((row, i) => {
    const smoothed = { ...row };
    cols.forEach((col) => {
      const start = Math.max(0, i - half);
      const end = Math.min(rows.length, i + half + 1);
      let sum = 0;
      let count = 0;
      for (let j = start; j < end; j++) {
        if (rows[j][col] != null && typeof rows[j][col] === "number") {
          sum += rows[j][col];
          count++;
        }
      }
      smoothed[col] = count > 0 ? sum / count : row[col];
    });
    return smoothed;
  });
}

export function getNumericColumns(rows) {
  if (!rows || rows.length === 0) return [];
  const cols = new Set();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (typeof row[key] === "number" && isFinite(row[key])) {
        cols.add(key);
      }
    });
  });
  return Array.from(cols);
}

export function getMetricColumns(rows) {
  return getNumericColumns(rows).filter((c) => !RESERVED_KEYS.includes(c));
}

export function computeMetricPlotData(masterData, xColumn, metric, xLim) {
  let relevant = masterData.filter(
    (r) => r[metric] != null && r[metric] !== undefined,
  );
  if (xLim) {
    const groups = new Map();
    for (const r of relevant) {
        const key = `${r.series_key || r.run || ""}\0${r.data_type || "original"}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    const filtered = [];
    for (const [, rows] of groups) {
      rows.sort((a, b) => a[xColumn] - b[xColumn]);
      let lo = 0;
      let hi = rows.length - 1;
      while (lo < rows.length && rows[lo][xColumn] < xLim[0]) lo++;
      while (hi >= 0 && rows[hi][xColumn] > xLim[1]) hi--;
      lo = Math.max(0, lo - 1);
      hi = Math.min(rows.length - 1, hi + 1);
      filtered.push(...rows.slice(lo, hi + 1));
    }
    relevant = filtered;
  }
  const originals = relevant.filter(
    (r) => r.data_type === "original" || !r.data_type,
  );
  let yExtent = undefined;
  if (originals.length > 0) {
    let yMin = Infinity;
    let yMax = -Infinity;
    for (const r of originals) {
      const v = r[metric];
      if (v != null) {
        if (v < yMin) yMin = v;
        if (v > yMax) yMax = v;
      }
    }
    if (yMin !== Infinity) yExtent = [yMin, yMax];
  }
  return {
    data: downsample(relevant, xColumn, metric, "series_key", xLim, [
      "run",
      "series_key",
    ]).data,
    yExtent,
  };
}

function downsampleImpl(data, x, y, colorField, xLim, extraFields = []) {
  const columns = [x, y];
  if (colorField && Object.hasOwn(data[0], colorField)) {
    columns.push(colorField);
  }
  columns.push(...extraFields);

  let filtered = data.map((r) => {
    const out = {};
    [...new Set(columns)].forEach((c) => (out[c] = r[c]));
    if (r.data_type) out.data_type = r.data_type;
    if (r.run) out.run = r.run;
    return out;
  });

  const dataXMin = Math.min(...filtered.map((r) => r[x]).filter((v) => v != null));
  const dataXMax = Math.max(...filtered.map((r) => r[x]).filter((v) => v != null));

  let updatedXLim = xLim;
  if (xLim) {
    const [xMin, xMax] = [xLim[0] ?? dataXMin, xLim[1] ?? dataXMax];
    updatedXLim = [xMin, xMax];
  }

  const groups = {};
  if (colorField) {
    filtered.forEach((r) => {
      const key = r[colorField] || "__default";
      if (!groups[key]) groups[key] = [];
      groups[key].push(r);
    });
  } else {
    groups["__default"] = filtered;
  }

  const result = [];
  const nBins = 100;

  Object.values(groups).forEach((groupData) => {
    groupData.sort((a, b) => (a[x] || 0) - (b[x] || 0));

    if (groupData.length < 500) {
      result.push(...groupData);
      return;
    }

    const gXMin = updatedXLim ? updatedXLim[0] : dataXMin;
    const gXMax = updatedXLim ? updatedXLim[1] : dataXMax;

    if (gXMin === gXMax) {
      result.push(...groupData);
      return;
    }

    const binSize = (gXMax - gXMin) / nBins;
    const bins = new Map();

    groupData.forEach((r) => {
      const val = r[x];
      if (val == null) return;
      const binIdx = Math.min(
        Math.floor((val - gXMin) / binSize),
        nBins - 1,
      );
      if (!bins.has(binIdx)) bins.set(binIdx, []);
      bins.get(binIdx).push(r);
    });

    bins.forEach((binData) => {
      if (binData.length === 0) return;
      let minRow = binData[0];
      let maxRow = binData[0];
      binData.forEach((r) => {
        if (r[y] < minRow[y]) minRow = r;
        if (r[y] > maxRow[y]) maxRow = r;
      });
      result.push(minRow);
      if (minRow !== maxRow) result.push(maxRow);
    });
  });

  result.sort((a, b) => (a[x] || 0) - (b[x] || 0));
  return { data: result, xLim: updatedXLim };
}

export function downsample(data, x, y, colorField, xLim, extraFields = []) {
  if (!data || data.length === 0) return { data, xLim };

  const splitByDataType =
    data.some((r) => r.data_type) &&
    colorField &&
    data[0] &&
    Object.hasOwn(data[0], colorField);

  if (splitByDataType) {
    const chunks = new Map();
    for (const r of data) {
      const key = `${r[colorField] ?? "__default"}\0${r.data_type ?? "original"}`;
      if (!chunks.has(key)) chunks.set(key, []);
      chunks.get(key).push(r);
    }
    const merged = [];
    let mergedXLim = xLim;
    for (const chunk of chunks.values()) {
      const out = downsampleImpl(chunk, x, y, colorField, xLim, extraFields);
      merged.push(...out.data);
      mergedXLim = out.xLim;
    }
    merged.sort((a, b) => (a[x] || 0) - (b[x] || 0));
    return { data: merged, xLim: mergedXLim };
  }

  return downsampleImpl(data, x, y, colorField, xLim, extraFields);
}

export function groupMetricsByPrefix(metrics, plotOrder = []) {
  const noPrefix = [];
  const withPrefix = {};

  metrics.forEach((m) => {
    if (m.includes("/")) {
      const parts = m.split("/");
      const prefix = parts[0];
      if (!withPrefix[prefix]) withPrefix[prefix] = { direct: [], subgroups: {} };
      if (parts.length === 2) {
        withPrefix[prefix].direct.push(m);
      } else {
        const sub = parts[1];
        if (!withPrefix[prefix].subgroups[sub])
          withPrefix[prefix].subgroups[sub] = [];
        withPrefix[prefix].subgroups[sub].push(m);
      }
    } else {
      noPrefix.push(m);
    }
  });

  function sortMetrics(items) {
    if (!plotOrder || plotOrder.length === 0) return items.sort();
    const ordered = [];
    const remaining = [...items];
    for (const pattern of plotOrder) {
      for (let i = remaining.length - 1; i >= 0; i--) {
        if (matchesPattern(remaining[i], pattern)) {
          ordered.push(remaining[i]);
          remaining.splice(i, 1);
        }
      }
    }
    remaining.sort();
    return [...ordered, ...remaining];
  }

  function matchesPattern(metric, pattern) {
    if (pattern === metric) return true;
    if (pattern.endsWith("/*") && metric.startsWith(pattern.slice(0, -1))) return true;
    if (pattern.includes("*")) {
      const re = new RegExp("^" + pattern.replace(/\*/g, ".*") + "$");
      return re.test(metric);
    }
    return false;
  }

  function getGroupPriority(groupName) {
    if (!plotOrder || plotOrder.length === 0) return Infinity;
    for (let i = 0; i < plotOrder.length; i++) {
      const patternGroup = plotOrder[i].includes("/") ? plotOrder[i].split("/")[0] : "charts";
      if (patternGroup === groupName) return i;
    }
    return Infinity;
  }

  const groups = {};
  if (noPrefix.length > 0) {
    groups["charts"] = { direct: sortMetrics(noPrefix), subgroups: {} };
  }

  const prefixKeys = Object.keys(withPrefix);
  prefixKeys.sort((a, b) => {
    const pa = getGroupPriority(a);
    const pb = getGroupPriority(b);
    if (pa !== pb) return pa - pb;
    return a.localeCompare(b);
  });

  prefixKeys.forEach((prefix) => {
    const g = withPrefix[prefix];
    g.direct = sortMetrics(g.direct);
    Object.keys(g.subgroups).forEach((s) => {
      g.subgroups[s] = sortMetrics(g.subgroups[s]);
    });
    groups[prefix] = g;
  });

  if ("charts" in groups) {
    const chartsPriority = getGroupPriority("charts");
    if (chartsPriority < Infinity) {
      const entries = Object.entries(groups);
      entries.sort(([a], [b]) => {
        const pa = a === "charts" ? chartsPriority : getGroupPriority(a);
        const pb = b === "charts" ? chartsPriority : getGroupPriority(b);
        if (pa !== pb) return pa - pb;
        return a.localeCompare(b);
      });
      const sorted = {};
      entries.forEach(([k, v]) => { sorted[k] = v; });
      return sorted;
    }
  }

  return groups;
}

export function buildColorSpecKey(data, colorField, colorMap) {
  if (!colorField || !data || data.length === 0) return "";
  const seen = new Set();
  const parts = [];
  for (const d of data) {
    const name = d[colorField];
    if (name && !seen.has(name)) {
      seen.add(name);
      parts.push(`${name}:${colorMap[name] ?? "#999"}`);
    }
  }
  parts.sort();
  return parts.join("|");
}

export function filterMetricsByRegex(metrics, pattern) {
  if (!pattern || !pattern.trim()) return metrics;
  try {
    const re = new RegExp(pattern, "i");
    return metrics.filter((m) => re.test(m));
  } catch {
    return metrics.filter((m) => m.toLowerCase().includes(pattern.toLowerCase()));
  }
}
