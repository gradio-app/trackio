import { afterEach, describe, expect, test } from "vitest";
import { applyUrlTokens } from "./urlTokens.js";

function setBrowser(protocol) {
  globalThis.document = { cookie: "" };
  globalThis.window = {
    location: {
      protocol,
      pathname: "/registry",
      search: "?write_token=secret",
    },
    history: { replaceState() {} },
  };
}

afterEach(() => {
  delete globalThis.document;
  delete globalThis.window;
});

describe("applyUrlTokens", () => {
  test("marks the write-token cookie secure over HTTPS", () => {
    setBrowser("https:");

    applyUrlTokens();

    expect(globalThis.document.cookie).toContain("; Secure");
  });

  test("allows the write-token cookie over local HTTP", () => {
    setBrowser("http:");

    applyUrlTokens();

    expect(globalThis.document.cookie).not.toContain("; Secure");
  });
});
