import { parquetRead } from "hyparquet";

const cache = new Map();

function coerceBigInts(row) {
  const out = {};
  for (const key in row) {
    const v = row[key];
    out[key] = typeof v === "bigint" ? Number(v) : v;
  }
  return out;
}

export async function readParquet(url, headers = {}) {
  if (cache.has(url)) return cache.get(url);

  const resp = await fetch(url, { headers });
  if (!resp.ok) {
    if (resp.status === 404) {
      cache.set(url, []);
      return [];
    }
    throw new Error(`Failed to fetch ${url}: ${resp.status}`);
  }

  const buffer = await resp.arrayBuffer();
  let rows = [];
  await parquetRead({
    file: buffer,
    rowFormat: "object",
    onComplete: (data) => {
      rows = data.map(coerceBigInts);
    },
  });

  cache.set(url, rows);
  return rows;
}

export function clearCache() {
  cache.clear();
}
