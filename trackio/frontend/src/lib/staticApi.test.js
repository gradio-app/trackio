import { afterEach, describe, expect, test, vi } from "vitest";
import { getConsoleLogs, initialize } from "./staticApi.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getConsoleLogs", () => {
  test("lists the run's non-empty console logs from the static media store", async () => {
    await initialize({ dataset_id: "user/data", project: "proj" });
    const sizes = {
      "https://huggingface.co/datasets/user/data/resolve/main/media/run-1/stdout-abc.log": "42",
      "https://huggingface.co/datasets/user/data/resolve/main/media/run-1/stderr-abc.log": "0",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => ({
        ok: url in sizes,
        headers: new Headers(url in sizes ? { "content-length": sizes[url] } : {}),
      })),
    );

    expect(await getConsoleLogs("run-1", "abc")).toEqual([
      { name: "stdout.log", path: "run-1/stdout-abc.log", size: 42 },
    ]);
  });
});
