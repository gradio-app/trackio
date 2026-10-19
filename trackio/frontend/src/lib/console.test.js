import { describe, expect, test } from "vitest";
import { formatConsoleTime, parseConsoleLines } from "./console.js";

describe("parseConsoleLines", () => {
  test("splits timestamped lines into local time and text", () => {
    const rows = parseConsoleLines(
      "2026-10-19T12:00:01Z INFO step 1\n2026-10-19T12:00:02Z   indented\n",
    );
    expect(rows).toEqual([
      { time: formatConsoleTime("2026-10-19T12:00:01Z"), text: "INFO step 1" },
      { time: formatConsoleTime("2026-10-19T12:00:02Z"), text: "  indented" },
    ]);
    expect(rows[0].time).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:01$/);
  });

  test("keeps lines without a timestamp and handles empty output", () => {
    expect(parseConsoleLines("no timestamp")).toEqual([{ time: "", text: "no timestamp" }]);
    expect(parseConsoleLines("")).toEqual([]);
  });
});
