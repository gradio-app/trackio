export function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function formatCompactNumber(value, precision = 4) {
  if (value == null) return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  if (Number.isInteger(num) && Math.abs(num) < 1e6) return String(num);
  return Number(num.toPrecision(precision)).toString();
}

/**
 * Truncates display text at `limit` UTF-16 code units, dropping a
 * trailing high surrogate so an emoji is never cut in half, and appends
 * an ellipsis.
 */
export function truncate(text, limit) {
  if (text.length <= limit) {
    return text;
  }
  let sliced = text.slice(0, limit);
  if (/[\uD800-\uDBFF]$/.test(sliced)) {
    sliced = sliced.slice(0, -1);
  }
  return sliced + "…";
}

export function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
