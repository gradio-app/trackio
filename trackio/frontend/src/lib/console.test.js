import { describe, expect, test } from "vitest";
import { formatConsoleTime, parseConsoleLines } from "./console.js";

describe("parseConsoleLines", () => {
  test("splits timestamped lines into time and text", () => {
    const rows = parseConsoleLines(
      "2026-10-19T12:00:01Z INFO step 1 loss=0.5\n2026-10-19T12:00:02Z   indented line\n",
    );
    expect(rows).toEqual([
      { time: formatConsoleTime("2026-10-19T12:00:01Z"), text: "INFO step 1 loss=0.5" },
      { time: formatConsoleTime("2026-10-19T12:00:02Z"), text: "  indented line" },
    ]);
  });

  test("keeps empty lines and lines without a timestamp", () => {
    expect(parseConsoleLines("2026-10-19T12:00:01Z \nno timestamp")).toEqual([
      { time: formatConsoleTime("2026-10-19T12:00:01Z"), text: "" },
      { time: "", text: "no timestamp" },
    ]);
  });

  test("returns no rows for empty output", () => {
    expect(parseConsoleLines("")).toEqual([]);
  });
});

describe("formatConsoleTime", () => {
  test("formats in local time and passes through invalid input", () => {
    const iso = "2026-10-19T12:00:01Z";
    const date = new Date(iso);
    expect(formatConsoleTime(iso)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:01$/);
    expect(formatConsoleTime(iso).startsWith(String(date.getFullYear()))).toBe(true);
    expect(formatConsoleTime("not a date")).toBe("not a date");
  });
});
