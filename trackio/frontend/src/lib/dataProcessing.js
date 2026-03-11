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
  runName,
  smoothingGranularity,
  xAxis,
  logScaleX,
  logScaleY,
) {
  if (!logs || logs.length === 0) return null;

  let rows = logs.map((row) => ({ ...row }));

  if (!rows[0].hasOwnProperty("step")) {
    rows.forEach((r, i) => (r.step = i));
  }

  let xColumn = "step";
  if (xAxis === "time" && rows[0].hasOwnProperty("timestamp")) {
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

  if (smoothingGranularity > 0) {
    const originals = rows.map((r) => ({
      ...r,
      run: runName,
      data_type: "original",
    }));
    const smoothed = smoothData(rows, yCols, smoothingGranularity).map(
      (r) => ({ ...r, run: runName + "_smoothed", data_type: "smoothed" }),
    );
    return { rows: [...originals, ...smoothed], xColumn };
  }

  return {
    rows: rows.map((r) => ({ ...r, run: runName, data_type: "original" })),
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

export function downsample(data, x, y, colorField, xLim) {
  if (!data || data.length === 0) return { data, xLim };

  const columns = [x, y];
  if (colorField && data[0].hasOwnProperty(colorField)) {
    columns.push(colorField);
  }

  let filtered = data.map((r) => {
    const out = {};
    columns.forEach((c) => (out[c] = r[c]));
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

export function groupMetricsByPrefix(metrics) {
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

  const groups = {};
  if (noPrefix.length > 0) {
    groups["charts"] = { direct: noPrefix.sort(), subgroups: {} };
  }
  Object.keys(withPrefix)
    .sort()
    .forEach((prefix) => {
      const g = withPrefix[prefix];
      g.direct.sort();
      Object.keys(g.subgroups).forEach((s) => g.subgroups[s].sort());
      groups[prefix] = g;
    });

  return groups;
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
