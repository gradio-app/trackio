import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  globalThis.window = { __trackio_base: "" };
});

afterEach(() => {
  vi.restoreAllMocks();
  delete globalThis.fetch;
  delete globalThis.window;
});

describe("getTrackioVersion", () => {
  test("returns the version reported by a live Trackio server", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ version: "0.37.2" }),
      });
    const { getTrackioVersion } = await import("./api.js");

    await expect(getTrackioVersion()).resolves.toBe("0.37.2");
    expect(globalThis.fetch).toHaveBeenNthCalledWith(1, "/config.json");
    expect(globalThis.fetch).toHaveBeenNthCalledWith(2, "/version");
  });

  test("returns the version embedded in a static dashboard", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ mode: "static", version: "0.37.2" }),
    });
    const { getTrackioVersion } = await import("./api.js");

    await expect(getTrackioVersion()).resolves.toBe("0.37.2");
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });
});
