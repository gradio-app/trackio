import { field as vegaField } from "vega";
import { describe, expect, test } from "vitest";

import { escapeVegaField } from "./vega.js";

describe("escapeVegaField", () => {
  test("leaves simple field names unchanged", () => {
    expect(escapeVegaField("train_loss")).toBe("train_loss");
  });

  test.each([
    "trainer.compute_loss",
    "metrics[0]",
    "literal\\backslash",
    "profiling/Time taken: GRPOTrainer.compute_loss",
  ])("makes the literal field %s accessible to Vega", (field) => {
    const row = { [field]: 0.25 };

    expect(vegaField(escapeVegaField(field))(row)).toBe(0.25);
  });
});
