import { describe, expect, test } from "vitest";
import golden from "./__fixtures__/lineage_golden.json";
import { buildLineage } from "./lineage.js";
import {
  edgePath,
  layoutLineage,
  mergeBidirectionalEdges,
  NODE_H,
  NODE_W,
} from "./lineageLayout.js";

function goldenGraph() {
  const tables = {
    artifacts: golden.artifacts,
    versions: golden.artifact_versions.map((v) => ({
      ...v,
      manifest: JSON.stringify(v.manifest),
    })),
    aliases: golden.artifact_aliases,
    links: golden.run_artifact_links,
  };
  return buildLineage(tables, golden.runs, golden.focus_version_id);
}

describe("layoutLineage", () => {
  test("positions every node with finite coordinates", () => {
    const graph = goldenGraph();
    const layout = layoutLineage(graph.nodes, graph.edges);
    expect(layout.nodes).toHaveLength(graph.nodes.length);
    for (const node of layout.nodes) {
      expect(Number.isFinite(node.x)).toBe(true);
      expect(Number.isFinite(node.y)).toBe(true);
      expect(node.width).toBe(NODE_W);
      expect(node.height).toBe(NODE_H);
    }
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.height).toBeGreaterThan(0);
  });

  test("ranks flow left to right along lineage", () => {
    const graph = goldenGraph();
    const layout = layoutLineage(graph.nodes, graph.edges);
    const x = Object.fromEntries(layout.nodes.map((n) => [n.id, n.x]));
    expect(x["run:prep-1"]).toBeLessThan(x["art:1"]);
    expect(x["art:1"]).toBeLessThan(x["run:train-b-1"]);
    expect(x["run:train-b-1"]).toBeLessThan(x["art:3"]);
    expect(x["art:3"]).toBeLessThan(x["run:eval-1"]);
    expect(x["run:eval-1"]).toBeLessThan(x["art:4"]);
  });

  test("drops edges whose endpoints are missing instead of emitting NaN", () => {
    const graph = goldenGraph();
    const nodes = graph.nodes.filter((n) => n.id !== "run:prep-1");
    const layout = layoutLineage(nodes, graph.edges);
    expect(layout.edges.some((e) => e.source === "run:prep-1")).toBe(false);
    for (const node of layout.nodes) {
      expect(Number.isFinite(node.x)).toBe(true);
    }
  });

  test("edge points are present for rendering", () => {
    const graph = goldenGraph();
    const layout = layoutLineage(graph.nodes, graph.edges);
    expect(layout.edges).toHaveLength(graph.edges.length);
    for (const edge of layout.edges) {
      expect(edge.points.length).toBeGreaterThanOrEqual(2);
    }
  });
});

describe("mergeBidirectionalEdges", () => {
  test("merges a produce+consume pair into one bidirectional edge", () => {
    const edges = [
      { source: "run:r", target: "art:1", direction: "output" },
      { source: "art:1", target: "run:r", direction: "input" },
    ];
    const merged = mergeBidirectionalEdges(edges);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      source: "run:r",
      target: "art:1",
      direction: "output",
      bidirectional: true,
    });
  });

  test("leaves one-directional edges untouched", () => {
    const edges = [
      { source: "run:r", target: "art:1", direction: "output" },
      { source: "art:1", target: "run:s", direction: "input" },
    ];
    const merged = mergeBidirectionalEdges(edges);
    expect(merged).toHaveLength(2);
    expect(merged.every((e) => e.bidirectional === false)).toBe(true);
  });
});

describe("edgePath", () => {
  test("two points produce a straight segment", () => {
    expect(edgePath([{ x: 0, y: 0 }, { x: 10, y: 5 }])).toBe("M 0 0 L 10 5");
  });

  test("interior points are smoothed with quadratic segments", () => {
    const d = edgePath([
      { x: 0, y: 0 },
      { x: 10, y: 10 },
      { x: 20, y: 0 },
    ]);
    expect(d).toBe("M 0 0 Q 10 10 20 0");
  });

  test("smoothing can be disabled for large graphs", () => {
    const d = edgePath(
      [
        { x: 0, y: 0 },
        { x: 10, y: 10 },
        { x: 20, y: 0 },
      ],
      false,
    );
    expect(d).toBe("M 0 0 L 10 10 L 20 0");
  });

  test("empty points produce an empty path", () => {
    expect(edgePath([])).toBe("");
  });
});
