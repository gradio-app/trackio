import { describe, expect, test, vi } from "vitest";

async function loadStaticApiWithRows(rows) {
  vi.resetModules();
  vi.doMock("./parquetReader.js", () => ({
    readParquet: vi.fn(async () => rows),
  }));
  const staticApi = await import("./staticApi.js");
  await staticApi.initialize({
    mode: "static",
    dataset_id: "owner/dataset",
    project: "proj",
  });
  return staticApi;
}

describe("staticApi.getLogs", () => {
  test("scalar_only returns only numeric metrics and structural fields", async () => {
    const staticApi = await loadStaticApiWithRows([
      {
        run_name: "run1",
        timestamp: "2026-06-19T12:00:00Z",
        step: 0,
        acc: 0.9,
        count: 3,
        done: true,
        note: "not plotted",
        table: JSON.stringify({
          _type: "trackio.table",
          _value: [{ prompt: "x".repeat(1000) }],
        }),
      },
    ]);

    await expect(
      staticApi.getLogs("proj", "run1", { scalar_only: true }),
    ).resolves.toEqual([
      {
        acc: 0.9,
        count: 3,
        timestamp: "2026-06-19T12:00:00Z",
        step: 0,
      },
    ]);
  });
});
