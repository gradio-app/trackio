const TIMESTAMP_RE = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) (.*)$/;

function pad(value) {
  return String(value).padStart(2, "0");
}

/**
 * Formats a UTC ISO timestamp from a console log line in the viewer's
 * local time zone.
 * @param {string} iso
 * @returns {string}
 */
export function formatConsoleTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

/**
 * Splits captured console output (one `<UTC timestamp> <text>` entry per
 * line) into rows for the run page's console viewer. Lines without a
 * timestamp prefix are kept with an empty time.
 * @param {string} text
 * @returns {Array<{time: string, text: string}>}
 */
export function parseConsoleLines(text) {
  if (!text) return [];
  const lines = text.endsWith("\n") ? text.slice(0, -1).split("\n") : text.split("\n");
  return lines.map((line) => {
    const match = TIMESTAMP_RE.exec(line);
    if (!match) return { time: "", text: line };
    return { time: formatConsoleTime(match[1]), text: match[2] };
  });
}
