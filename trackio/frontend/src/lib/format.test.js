import { describe, expect, test } from "vitest";

import { formatCompactNumber, truncate } from "./format.js";

describe("formatCompactNumber", () => {
  test("returns an em dash for null and undefined", () => {
    expect(formatCompactNumber(null)).toBe("—");
    expect(formatCompactNumber(undefined)).toBe("—");
  });

  test("keeps small integers verbatim", () => {
    expect(formatCompactNumber(5)).toBe("5");
    expect(formatCompactNumber(-42)).toBe("-42");
  });

  test("rounds non-integers to the given precision", () => {
    expect(formatCompactNumber(0.123456)).toBe("0.1235");
    expect(formatCompactNumber(0.123456, 3)).toBe("0.123");
  });

  test("drops trailing zeros", () => {
    expect(formatCompactNumber(1.5)).toBe("1.5");
  });

  test("compacts large integers", () => {
    expect(formatCompactNumber(1234567)).toBe("1235000");
  });

  test("stringifies non-numeric values", () => {
    expect(formatCompactNumber("abc")).toBe("abc");
  });
});

describe("truncate", () => {
  test("returns short text unchanged", () => {
    expect(truncate("hello", 10)).toBe("hello");
  });

  test("truncates long text with an ellipsis", () => {
    expect(truncate("hello world", 5)).toBe("hello…");
  });

  test("never cuts a surrogate pair in half", () => {
    expect(truncate("ab😀cd", 3)).toBe("ab…");
  });
});
