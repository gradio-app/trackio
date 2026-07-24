import { PROMOTED_RESERVED_KEYS } from "./grouping.js";

/**
 * Maximum number of run columns the comparer displays.
 */
export const COMPARER_MAX_COLUMNS = 10;

/**
 * Rendered in place of a value for keys a run never logged.
 */
export const MISSING_MARKER = "–";

/**
 * Display labels for the reserved config keys surfaced in the
 * Metadata section, keyed by storage name (`_Created` → "Created").
 */
export const METADATA_LABELS = Object.freeze({
  _Created: "Created",
  ...PROMOTED_RESERVED_KEYS,
});

const METADATA_ORDER = ["_Created", ...Object.keys(PROMOTED_RESERVED_KEYS)];

/**
 * Canonical identity of a run for lookups: the stable `id` when present,
 * `name` for legacy rows — the same convention the rest of the dashboard
 * uses to key caches, configs, and colors.
 * @param {{id?: string, name?: string} | null | undefined} run
 * @returns {string | undefined}
 */
export function runKeyOf(run) {
  return run?.id ?? run?.name;
}

/**
 * Only plain objects are traversed (including prototype-less ones, like
 * the maps buildComparerRows feeds into flattenConfig). Anything else —
 * arrays, Dates, Maps — is considered a leaf.
 */
function isTraversable(value) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

const BIGINT_SAFE_MAX = BigInt(Number.MAX_SAFE_INTEGER);
const BIGINT_SAFE_MIN = BigInt(Number.MIN_SAFE_INTEGER);

/**
 * Narrows a BigInt (hyparquet yields them for int64 parquet columns in
 * static mode) to a plain number when it fits the safe-integer range, and
 * to a decimal string otherwise so precision is never silently lost.
 * @param {bigint} value
 * @returns {number | string}
 */
function fromBigInt(value) {
  if (value <= BIGINT_SAFE_MAX && value >= BIGINT_SAFE_MIN) {
    return Number(value);
  }
  return value.toString();
}

/**
 * Escapes backslashes and dots inside a key segment so joining segments
 * with "." stays bijective: distinct config structures always produce
 * distinct paths, and no value can shadow another.
 */
function escapeSegment(segment) {
  return segment.replace(/\\/g, "\\\\").replace(/\./g, "\\.");
}

/**
 * Flattens a nested config into dot-path keys (`optimizer.lr`).
 * Arrays and other non-plain-object values are leaves, and empty-object
 * leaves produce no entry. A dot inside a literal key is escaped
 * (`{"a.b": 1}` → `a\.b`), keeping it distinct from the nested path
 * (`{a: {b: 2}}` → `a.b`) so both values are always shown. The result is a
 * prototype-less map so a key literally named `__proto__` stays data.
 * @param {unknown} config
 * @returns {Record<string, unknown>} escaped dot-path → leaf value
 */
export function flattenConfig(config) {
  const flat = Object.create(null);
  if (!isTraversable(config)) {
    return flat;
  }
  const walk = (obj, prefix) => {
    for (const [key, value] of Object.entries(obj)) {
      const segment = escapeSegment(key);
      const path = prefix === null ? segment : `${prefix}.${segment}`;
      if (isTraversable(value)) {
        walk(value, path);
      } else if (typeof value === "bigint") {
        flat[path] = fromBigInt(value);
      } else {
        flat[path] = value;
      }
    }
  };
  walk(config, null);
  return flat;
}

/**
 * Serializes with object keys recursively sorted, so deep-equal objects
 * canonicalize identically even when the fields are ordered differently.
 * Also used as the display/copy serialization in formatCellValue for
 * object/array values, so two such cells render identically exactly when
 * they compare equal. Out-of-range BigInts become quoted strings,
 * matching flattenConfig's leaf treatment and keeping copied JSON
 * reparse-safe.
 */
function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (isTraversable(value)) {
    const parts = Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`);
    return `{${parts.join(",")}}`;
  }
  if (typeof value === "bigint") {
    return JSON.stringify(fromBigInt(value));
  }
  const encoded = JSON.stringify(value);
  return encoded === undefined ? "null" : encoded;
}

/**
 * Type-tagged canonical form used for cell equality: `1` and `"1"` stay
 * distinct, NaN equals NaN, and `null` is a real value while `undefined`
 * means the key is absent from that run. BigInts deliberately share the
 * `number:` tag (via fromBigInt): an int64 read from parquet in static
 * mode must equal the same value arriving as a JSON number in live mode.
 */
function canonicalize(value) {
  if (value === undefined) return "missing:";
  if (value === null) return "null:";
  switch (typeof value) {
    case "number":
      return Number.isNaN(value) ? "number:NaN" : `number:${value}`;
    case "bigint":
      return `number:${fromBigInt(value)}`;
    case "boolean":
      return `boolean:${value}`;
    case "string":
      return `string:${value}`;
    default:
      return `json:${stableStringify(value)}`;
  }
}

/**
 * Whether a row's values differ across the displayed runs. A key missing
 * from only some runs counts as a difference; a key missing from all of
 * them does not.
 * @param {unknown[]} values one slot per run, `undefined` = missing
 * @param {number} count number of run slots to compare
 * @returns {boolean}
 */
export function rowDiffers(values, count) {
  const seen = new Set();
  for (let i = 0; i < count; i++) {
    seen.add(canonicalize(values[i]));
    if (seen.size > 1) return true;
  }
  return false;
}

function configForRun(run, runConfigs) {
  const cfg = (runConfigs ?? {})[run?.id] ?? (runConfigs ?? {})[run?.name];
  return isTraversable(cfg) ? cfg : {};
}

function sortedUnion(keyLists) {
  const keys = new Set();
  for (const list of keyLists) {
    for (const key of list) keys.add(key);
  }
  return [...keys].sort((a, b) => a.localeCompare(b));
}

/**
 * @typedef {Object} ComparerRow
 * @property {"config" | "metadata"} section
 * @property {string} key storage key, dot-flattened for config entries
 * @property {string} label text shown in the sticky key column
 * @property {unknown[]} values one slot per displayed run; `undefined` = missing
 * @property {boolean} differs true when values are not identical across runs
 */

function sectionRows(section, sources, count) {
  return sortedUnion(sources.map(Object.keys)).map((key) => {
    const values = sources.map((source) =>
      Object.hasOwn(source, key) ? source[key] : undefined,
    );
    return {
      section,
      key,
      label: key,
      values,
      differs: rowDiffers(values, count),
    };
  });
}

/**
 * Builds the comparer's rows for the displayed runs: the union of their
 * flattened config keys, sorted, with `_`-reserved keys excluded, followed
 * by the Metadata section. Configs are resolved per run by id first and
 * name second, and reserved metadata values of `null` ("not set") are
 * treated as missing so live and static modes render identically.
 * @param {Array<{id?: string, name?: string}>} runs runs in display order
 * @param {Record<string, object>} runConfigs configs keyed by run id or name
 * @returns {ComparerRow[]}
 */
export function buildComparerRows(runs, runConfigs) {
  const count = runs.length;
  const rawConfigs = runs.map((run) => configForRun(run, runConfigs));
  const flatConfigs = rawConfigs.map((cfg) => {
    const visible = Object.create(null);
    for (const [key, value] of Object.entries(cfg)) {
      if (!key.startsWith("_")) {
        visible[key] = value;
      }
    }
    return flattenConfig(visible);
  });
  const rows = sectionRows("config", flatConfigs, count);
  for (const key of METADATA_ORDER) {
    const values = rawConfigs.map((cfg) => {
      const value = Object.hasOwn(cfg, key) ? cfg[key] : undefined;
      return value === null ? undefined : value;
    });
    if (!values.some((v) => v !== undefined)) continue;
    rows.push({
      section: "metadata",
      key,
      label: METADATA_LABELS[key],
      values,
      differs: rowDiffers(values, count),
    });
  }
  return rows;
}

/**
 * Applies the panel's two filters: a case-insensitive substring match over
 * row keys and labels composed with the "Diff only" toggle.
 * @param {ComparerRow[]} rows
 * @param {string} searchText
 * @param {boolean} diffOnly
 * @returns {ComparerRow[]}
 */
export function filterComparerRows(rows, searchText, diffOnly) {
  const needle = (searchText ?? "").trim().toLowerCase();
  return rows.filter((row) => {
    if (diffOnly && !row.differs) return false;
    if (!needle) return true;
    return (
      row.key.toLowerCase().includes(needle) ||
      row.label.toLowerCase().includes(needle)
    );
  });
}

/**
 * Whether a string's raw text could be mistaken for another value's
 * rendering, so it needs its JSON-quoted form to stay distinguishable:
 * anything some number renders as (`"1"`, `"NaN"`), the boolean/null
 * words, JSON-looking text, the missing marker, and empty or
 * whitespace-padded strings that would otherwise be invisible.
 */
function isAmbiguousString(value) {
  if (value === "" || value !== value.trim()) return true;
  if (value === "true" || value === "false" || value === "null") return true;
  if (value === MISSING_MARKER) return true;
  if (value.startsWith("{") || value.startsWith("[")) return true;
  return String(Number(value)) === value;
}

/**
 * Formats a cell for rendering and copying. `text` is always the full,
 * untruncated value — display truncation is the component's concern, and
 * the copy button must receive everything — while `missing` marks keys the
 * run never had, rendered as the missing marker. Strings render raw for
 * readability unless the raw text is ambiguous (see isAmbiguousString);
 * those render JSON-quoted so `1` and `"1"` stay visually distinct.
 * Together with stableStringify for object values, two cells render
 * identically exactly when rowDiffers considers them equal.
 * @param {unknown} value
 * @returns {{text: string, missing: boolean}}
 */
export function formatCellValue(value) {
  if (value === undefined) {
    return { text: "", missing: true };
  }
  if (value === null) {
    return { text: "null", missing: false };
  }
  switch (typeof value) {
    case "string":
      return {
        text: isAmbiguousString(value) ? JSON.stringify(value) : value,
        missing: false,
      };
    case "number":
    case "boolean":
    case "bigint":
      return { text: String(value), missing: false };
    default:
      return { text: stableStringify(value), missing: false };
  }
}
