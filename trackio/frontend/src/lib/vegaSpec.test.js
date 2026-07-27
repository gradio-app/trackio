import { parse, View } from "vega";
import { compile } from "vega-lite";
import { describe, expect, test } from "vitest";
import {
  buildAxisLabelExpression,
  VEGA_LITE_SCHEMA,
} from "./vegaSpec.js";

describe("Vega chart safety", () => {
  test("keeps hostile run labels inside an escaped expression string", () => {
    const expression = buildAxisLabelExpression({
      'run"]; setdata("metrics", []); //': "</script><img src=x onerror=alert(1)>",
      separators: "line\u2028paragraph\u2029end",
    });

    expect(expression).not.toContain("<");
    expect(expression).not.toContain(">");
    expect(expression).not.toContain("&");
    expect(expression).not.toContain("\u2028");
    expect(expression).not.toContain("\u2029");
    expect(expression).toContain("\\u003c/script\\u003e");
  });

  test("Vega 6 compiles and evaluates representative Trackio chart values", async () => {
    const hostileKey = 'run"]; setdata("metrics", []); //';
    const hostileLabel = "</script><img src=x onerror=alert(1)>";
    const spec = {
      $schema: VEGA_LITE_SCHEMA,
      data: {
        values: [{ key: hostileKey, label: hostileLabel, value: 0.5 }],
      },
      mark: { type: "bar" },
      encoding: {
        x: {
          field: "key",
          type: "nominal",
          axis: {
            labelExpr: buildAxisLabelExpression({
              [hostileKey]: hostileLabel,
            }),
          },
        },
        y: { field: "value", type: "quantitative" },
        tooltip: [
          { field: "label", type: "nominal" },
          { field: "value", type: "quantitative" },
        ],
      },
    };

    const { spec: compiled } = compile(spec);
    const view = new View(parse(compiled), { renderer: "none" });
    await expect(view.runAsync()).resolves.toBe(view);
    view.finalize();
  });
});
