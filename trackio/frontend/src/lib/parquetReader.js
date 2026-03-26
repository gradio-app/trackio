import { parquetRead } from "hyparquet";

const cache = new Map();

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
    onComplete: (data) => {
      rows = data;
    },
  });

  cache.set(url, rows);
  return rows;
}

export function clearCache() {
  cache.clear();
}
