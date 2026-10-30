import { afterEach, describe, expect, test } from "vitest";
import {
  applyUrlTokens,
  getSavedWriteToken,
  getWriteTokenHeader,
  saveWriteToken,
} from "./urlTokens.js";

function setBrowser(protocol, search = "?write_token=secret", stored = {}) {
  globalThis.document = { cookie: "" };
  globalThis.window = {
    location: {
      protocol,
      pathname: "/registry",
      search,
    },
    history: { replaceState() {} },
  };
  globalThis.localStorage = {
    getItem: (key) => stored[key] ?? null,
    setItem: (key, value) => {
      stored[key] = value;
    },
    removeItem: (key) => {
      delete stored[key];
    },
  };
  return stored;
}

afterEach(() => {
  delete globalThis.document;
  delete globalThis.window;
  delete globalThis.localStorage;
});

describe("saved write token", () => {
  test("a token from the URL is kept in local storage", () => {
    setBrowser("http:");

    applyUrlTokens();

    expect(getSavedWriteToken()).toBe("secret");
  });

  test("a saved token sets the cookie when the URL has none", () => {
    setBrowser("http:", "", { trackio_write_token: "saved" });

    applyUrlTokens();

    expect(globalThis.document.cookie).toContain("trackio_write_token=saved;");
  });

  test("saving an empty token clears storage and expires the cookie", () => {
    const stored = setBrowser("http:", "", { trackio_write_token: "saved" });

    saveWriteToken("");

    expect(stored).toEqual({});
    expect(globalThis.document.cookie).toContain("max-age=0");
  });

  test("a saved token is sent as a request header for embedded dashboards", () => {
    setBrowser("http:", "", { trackio_write_token: "saved" });
    expect(getWriteTokenHeader()).toEqual({ "x-trackio-write-token": "saved" });

    saveWriteToken("");
    expect(getWriteTokenHeader()).toEqual({});
  });
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
