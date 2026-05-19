import { beforeEach, describe, expect, test, vi } from "vitest";

function jsonResponse(data, ok = true, status = 200) {
  return {
    ok,
    status,
    async json() {
      return data;
    },
  };
}

async function loadApi() {
  vi.resetModules();
  globalThis.window = { __trackio_base: "" };
  globalThis.sessionStorage = {
    getItem: vi.fn(() => null),
  };
  return await import("./api.js");
}

describe("getScalarLogsBatch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    delete globalThis.fetch;
    delete globalThis.window;
    delete globalThis.sessionStorage;
  });

  test("returns all scalar query rows without fetching trace payloads", async () => {
    const queryRows = Array.from({ length: 1601 }, (_, index) => ({
      timestamp: `2026-01-01T00:${String(index % 60).padStart(2, "0")}:00Z`,
      step: index,
      metrics: JSON.stringify({ "train/loss": index, "train/lr": index / 1000 }),
    }));

    let query = "";
    const fetch = vi.fn(async (url, options) => {
      if (url === "/config.json") {
        return jsonResponse({ mode: "server" });
      }
      if (url === "/api/query_project") {
        const body = JSON.parse(options.body);
        query = body.query;
        return jsonResponse({
          data: {
            rows: queryRows,
          },
        });
      }
      throw new Error(`Unexpected fetch URL: ${url}`);
    });
    globalThis.fetch = fetch;

    const { getScalarLogsBatch } = await loadApi();
    const result = await getScalarLogsBatch("proj", [{ id: "run-1", name: "run-name" }]);

    expect(result).toHaveLength(1);
    expect(result[0].logs).toHaveLength(queryRows.length);
    expect(result[0].logs[1600]).toMatchObject({
      timestamp: queryRows[1600].timestamp,
      step: 1600,
      "train/loss": 1600,
      "train/lr": 1.6,
    });

    expect(query).toContain("AND j.type IN ('integer', 'real')");
    expect(query).toContain("GROUP BY m.id, m.timestamp, m.step");
    expect(query).toContain("ORDER BY timestamp");
    expect(query).not.toContain("ROW_NUMBER");
    expect(query).not.toContain("row_count");
    expect(query).not.toContain("1500");
  });
});
