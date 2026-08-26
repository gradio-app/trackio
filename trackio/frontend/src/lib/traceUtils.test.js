import { describe, expect, it } from "vitest";

import {
  flattenSpanTree,
  formatCost,
  formatDuration,
  messageToolSpans,
  spanDurationMs,
  traceSummary,
} from "./traceUtils.js";

describe("traceUtils", () => {
  it("builds a stable parent-child execution tree", () => {
    const rows = flattenSpanTree([
      { id: "tool", parent_id: "agent", name: "hf search", kind: "tool" },
      { id: "agent", name: "research", kind: "span" },
      { id: "model", parent_id: "agent", name: "provider", kind: "generation" },
    ]);

    expect(rows.map((row) => [row.id, row.depth])).toEqual([
      ["agent", 0],
      ["tool", 1],
      ["model", 1],
    ]);
    expect(rows[0].hasChildren).toBe(true);
  });

  it("omits descendants of collapsed spans", () => {
    const rows = flattenSpanTree(
      [
        { id: "agent", name: "research" },
        { id: "tool", parent_id: "agent", name: "hf search" },
      ],
      new Set(["agent"]),
    );

    expect(rows.map((row) => row.id)).toEqual(["agent"]);
  });

  it("derives tool spans from existing OpenAI-style messages", () => {
    const spans = messageToolSpans([
      {
        role: "assistant",
        tool_calls: [
          {
            id: "call-1",
            function: { name: "hf", arguments: '{"query":"agent data"}' },
          },
        ],
      },
      {
        role: "tool",
        tool_call_id: "call-1",
        content: '{"matches":3}',
      },
    ]);

    expect(spans).toHaveLength(1);
    expect(spans[0]).toMatchObject({
      id: "call-1",
      name: "hf",
      input: { query: "agent data" },
      output: { matches: 3 },
      status: null,
    });
  });

  it("summarizes wall-clock latency, usage, cost, and errors", () => {
    const summary = traceSummary({
      spans: [
        {
          id: "generation",
          start_time: "2026-08-19T12:00:00.000Z",
          end_time: "2026-08-19T12:00:02.000Z",
          usage: { input_tokens: 100, output_tokens: 20 },
          cost_usd: 0.002,
          status: "success",
        },
        {
          id: "tool",
          start_time: "2026-08-19T12:00:01.500Z",
          end_time: "2026-08-19T12:00:03.000Z",
          cost_usd: 0.001,
          status: "error",
        },
      ],
    });

    expect(summary).toMatchObject({
      durationMs: 3000,
      costUsd: 0.003,
      inputTokens: 100,
      outputTokens: 20,
      totalTokens: 120,
      status: "error",
      spanCount: 2,
    });
  });

  it("does not assume success from an OpenAI-style tool result", () => {
    const trace = {
      messages: [
        {
          role: "assistant",
          tool_calls: [{ id: "call-1", function: { name: "hf", arguments: "{}" } }],
        },
        { role: "tool", tool_call_id: "call-1", content: "ok" },
      ],
    };

    expect(messageToolSpans(trace.messages)[0].status).toBe(null);
    expect(traceSummary(trace).status).toBe(null);
  });

  it("marks a derived tool operation failed from an error flag", () => {
    const spans = messageToolSpans([
      {
        role: "assistant",
        tool_calls: [{ id: "call-1", function: { name: "hf", arguments: "{}" } }],
      },
      { role: "tool", tool_call_id: "call-1", is_error: true, content: "boom" },
    ]);

    expect(spans[0].status).toBe("error");
    expect(traceSummary({ spans }).status).toBe("error");
  });

  it("ignores a non-string trace metadata status", () => {
    expect(traceSummary({ spans: [], metadata: { status: { code: 2 } } }).status).toBe(
      null,
    );
  });

  it("formats span metrics compactly", () => {
    expect(spanDurationMs({ duration_ms: 750 })).toBe(750);
    expect(traceSummary({ spans: [{ duration_ms: 750 }] }).durationMs).toBe(750);
    expect(formatDuration(23790)).toBe("23.8s");
    expect(formatCost(0.00425)).toBe("$0.0043");
  });
});
