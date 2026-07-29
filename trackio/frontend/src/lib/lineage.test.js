import { describe, expect, test } from "vitest";
import { golden, goldenTables } from "./__fixtures__/lineageGolden.js";
import {
  buildLineage,
  buildRunOwnership,
  canonicalLinkRunId,
  clusterLineage,
} from "./lineage.js";

describe("buildLineage", () => {
  test("matches the golden fixture shared with the server tests", () => {
    const result = buildLineage(
      goldenTables(),
      golden.runs,
      golden.focus_version_id,
    );
    expect(result).toEqual(golden.expected);
  });

  test("synthesizes run records for artifact-only runs absent from runs.json", () => {
    const result = buildLineage(goldenTables(), golden.runs, 4);
    const evalRun = result.nodes.find((n) => n.id === "run:eval-1");
    expect(evalRun).toBeTruthy();
    expect(evalRun.run_id).toBe("eval-1");
  });

  test("returns a single node for a version with no links", () => {
    const tables = goldenTables();
    tables.versions = [
      ...tables.versions,
      {
        id: 99,
        artifact_id: 1,
        version: 1,
        manifest: "[]",
        manifest_digest: "digest-orphan",
        metadata: null,
        size_bytes: 0,
        producer_run_id: null,
        producer_run_name: null,
        created_at: "2026-01-02T00:00:00+00:00",
      },
    ];
    const result = buildLineage(tables, golden.runs, 99);
    expect(result.edges).toEqual([]);
    expect(result.nodes).toHaveLength(1);
    expect(result.nodes[0]).toMatchObject({
      id: "art:99",
      producer_run_id: null,
      producer_run_name: null,
      num_files: 0,
    });
  });

  test("returns empty graph for an unknown version", () => {
    const result = buildLineage(goldenTables(), golden.runs, 12345);
    expect(result).toEqual({
      focus: "art:12345",
      truncated: false,
      nodes: [],
      edges: [],
    });
  });

  test("excludes disconnected components", () => {
    const tables = goldenTables();
    tables.artifacts = [
      ...tables.artifacts,
      {
        id: 9,
        name: "other",
        type: "dataset",
        description: null,
        created_at: "2026-01-03T00:00:00+00:00",
      },
    ];
    tables.versions = [
      ...tables.versions,
      {
        id: 90,
        artifact_id: 9,
        version: 0,
        manifest: "[]",
        manifest_digest: "digest-other",
        metadata: null,
        size_bytes: 0,
        producer_run_id: "solo-1",
        producer_run_name: "solo",
        created_at: "2026-01-03T00:00:00+00:00",
      },
    ];
    tables.links = [
      ...tables.links,
      {
        id: 90,
        run_id: "solo-1",
        run_name: "solo",
        artifact_version_id: 90,
        direction: "output",
        created_at: "2026-01-03T00:00:00+00:00",
      },
    ];
    const result = buildLineage(tables, golden.runs, 90);
    expect(new Set(result.nodes.map((n) => n.id))).toEqual(
      new Set(["art:90", "run:solo-1"]),
    );
  });

  test("dedupes duplicate links and folds orphan run ids by name", () => {
    const tables = goldenTables();
    tables.links = [
      ...tables.links,
      {
        id: 91,
        run_id: "unknown-id",
        run_name: "prepare",
        artifact_version_id: 1,
        direction: "output",
        created_at: "2026-01-04T00:00:00+00:00",
      },
      {
        id: 92,
        run_id: null,
        run_name: "prepare",
        artifact_version_id: 1,
        direction: "output",
        created_at: "2026-01-04T00:00:01+00:00",
      },
    ];
    const result = buildLineage(tables, golden.runs, golden.focus_version_id);
    expect(result).toEqual(golden.expected);
  });

  test("keeps a run producing and consuming the same version as two edges", () => {
    const tables = {
      artifacts: [
        {
          id: 1,
          name: "state",
          type: "checkpoint",
          description: null,
          created_at: "2026-01-01T00:00:00+00:00",
        },
      ],
      versions: [
        {
          id: 1,
          artifact_id: 1,
          version: 0,
          manifest: "[]",
          manifest_digest: "d",
          metadata: null,
          size_bytes: 0,
          producer_run_id: "r-1",
          producer_run_name: "loop",
          created_at: "2026-01-01T00:00:00+00:00",
        },
      ],
      aliases: [],
      links: [
        {
          id: 1,
          run_id: "r-1",
          run_name: "loop",
          artifact_version_id: 1,
          direction: "output",
          created_at: "2026-01-01T00:00:00+00:00",
        },
        {
          id: 2,
          run_id: "r-1",
          run_name: "loop",
          artifact_version_id: 1,
          direction: "input",
          created_at: "2026-01-01T00:00:01+00:00",
        },
      ],
    };
    const result = buildLineage(tables, [], 1);
    expect(result.edges).toHaveLength(2);
    expect(result.edges.map((e) => e.direction).sort()).toEqual([
      "input",
      "output",
    ]);
  });

  test("terminates on cyclic lineage", () => {
    const version = (id) => ({
      id,
      artifact_id: 1,
      version: id,
      manifest: "[]",
      manifest_digest: `d${id}`,
      metadata: null,
      size_bytes: 0,
      producer_run_id: null,
      producer_run_name: null,
      created_at: "2026-01-01T00:00:00+00:00",
    });
    const link = (id, runId, versionId, direction) => ({
      id,
      run_id: runId,
      run_name: runId,
      artifact_version_id: versionId,
      direction,
      created_at: `2026-01-01T00:00:0${id}+00:00`,
    });
    const tables = {
      artifacts: [
        {
          id: 1,
          name: "a",
          type: "t",
          description: null,
          created_at: "2026-01-01T00:00:00+00:00",
        },
      ],
      versions: [version(1), version(2)],
      aliases: [],
      links: [
        link(1, "run-a", 1, "output"),
        link(2, "run-a", 2, "input"),
        link(3, "run-b", 1, "input"),
        link(4, "run-b", 2, "output"),
      ],
    };
    const result = buildLineage(tables, [], 1);
    expect(result.nodes).toHaveLength(4);
    expect(result.edges).toHaveLength(4);
  });
});

describe("buildRunOwnership / canonicalLinkRunId", () => {
  test("keeps existing runs.json ownership behavior", () => {
    const ownership = buildRunOwnership([{ id: "id-1", name: "train" }], []);
    expect(
      canonicalLinkRunId({ run_id: "id-1", run_name: "train" }, ownership),
    ).toBe("id-1");
    expect(
      canonicalLinkRunId({ run_id: null, run_name: "train" }, ownership),
    ).toBe("id-1");
    expect(
      canonicalLinkRunId({ run_id: null, run_name: "unknown" }, ownership),
    ).toBe(null);
  });

  test("ambiguous names do not fold", () => {
    const ownership = buildRunOwnership(
      [
        { id: "id-1", name: "train" },
        { id: "id-2", name: "train" },
      ],
      [],
    );
    expect(
      canonicalLinkRunId({ run_id: null, run_name: "train" }, ownership),
    ).toBe(null);
  });

  test("links with names already known to runs.json add no records", () => {
    const ownership = buildRunOwnership(
      [{ id: "id-1", name: "train" }],
      [{ run_id: "other-id", run_name: "train" }],
    );
    expect(ownership.recordIds.has("other-id")).toBe(false);
  });
});

describe("clusterLineage", () => {
  const goldenGraph = buildLineage(
    goldenTables(),
    golden.runs,
    golden.focus_version_id,
  );

  function fanOutGraph(count) {
    const nodes = [
      { id: "run:r-1", kind: "run", run_id: "r-1", run_name: "train" },
    ];
    const edges = [];
    for (let i = 1; i <= count; i++) {
      nodes.push({
        id: `art:${i}`,
        kind: "artifact",
        version_id: i,
        artifact_name: "ckpt",
        artifact_type: "checkpoint",
        version: i,
        created_at: `2026-01-01T00:00:0${i}+00:00`,
      });
      edges.push({
        source: "run:r-1",
        target: `art:${i}`,
        direction: "output",
        created_at: `2026-01-01T00:00:0${i}+00:00`,
      });
    }
    return { focus: "art:1", truncated: false, nodes, edges };
  }

  test("leaves small graphs untouched", () => {
    const clustered = clusterLineage(goldenGraph, "art:3");
    expect(clustered.nodes).toEqual(goldenGraph.nodes);
    expect(clustered.edges).toEqual(goldenGraph.edges);
  });

  test("groups five or more similarly-connected nodes into one cluster", () => {
    const graph = fanOutGraph(6);
    const clustered = clusterLineage(graph, "art:1");
    const cluster = clustered.nodes.find((n) => n.kind === "cluster");
    expect(cluster).toBeTruthy();
    expect(cluster.member_kind).toBe("artifact");
    expect(cluster.count).toBe(5);
    expect(cluster.members.map((m) => m.id)).toEqual([
      "art:2",
      "art:3",
      "art:4",
      "art:5",
      "art:6",
    ]);
    expect(new Set(clustered.nodes.map((n) => n.id))).toEqual(
      new Set(["run:r-1", "art:1", cluster.id]),
    );
  });

  test("rewrites and dedupes edges into the cluster", () => {
    const graph = fanOutGraph(6);
    const clustered = clusterLineage(graph, "art:1");
    const cluster = clustered.nodes.find((n) => n.kind === "cluster");
    const clusterEdges = clustered.edges.filter((e) => e.target === cluster.id);
    expect(clusterEdges).toHaveLength(1);
    expect(clusterEdges[0]).toMatchObject({
      source: "run:r-1",
      direction: "output",
      created_at: "2026-01-01T00:00:02+00:00",
    });
    expect(clustered.edges).toHaveLength(2);
  });

  test("never clusters the focus node", () => {
    const graph = fanOutGraph(6);
    const clustered = clusterLineage(graph, "art:4");
    const cluster = clustered.nodes.find((n) => n.kind === "cluster");
    expect(cluster.members.some((m) => m.id === "art:4")).toBe(false);
    expect(clustered.nodes.some((n) => n.id === "art:4")).toBe(true);
  });

  test("nodes with extra connections stay out of the cluster", () => {
    const graph = fanOutGraph(7);
    graph.nodes.push({
      id: "run:eval",
      kind: "run",
      run_id: "eval",
      run_name: "eval",
    });
    graph.edges.push({
      source: "art:7",
      target: "run:eval",
      direction: "input",
      created_at: "2026-01-01T00:01:00+00:00",
    });
    const clustered = clusterLineage(graph, "art:1");
    const cluster = clustered.nodes.find((n) => n.kind === "cluster");
    expect(cluster.count).toBe(5);
    expect(cluster.members.some((m) => m.id === "art:7")).toBe(false);
    expect(clustered.nodes.some((n) => n.id === "art:7")).toBe(true);
  });

  test("extracted members become individual nodes with their own edges", () => {
    const graph = fanOutGraph(6);
    const clustered = clusterLineage(graph, "art:1", {
      extracted: new Set(["art:3"]),
    });
    const cluster = clustered.nodes.find((n) => n.kind === "cluster");
    expect(cluster.count).toBe(4);
    expect(clustered.nodes.some((n) => n.id === "art:3")).toBe(true);
    expect(
      clustered.edges.some(
        (e) => e.source === "run:r-1" && e.target === "art:3",
      ),
    ).toBe(true);
  });

  test("cluster id is stable across extractions", () => {
    const graph = fanOutGraph(6);
    const before = clusterLineage(graph, "art:1");
    const after = clusterLineage(graph, "art:1", {
      extracted: new Set(["art:2"]),
    });
    expect(after.nodes.find((n) => n.kind === "cluster").id).toBe(
      before.nodes.find((n) => n.kind === "cluster").id,
    );
  });

  test("dissolves the cluster when fewer than two members remain", () => {
    const graph = fanOutGraph(6);
    const clustered = clusterLineage(graph, "art:1", {
      extracted: new Set(["art:2", "art:3", "art:4", "art:5"]),
    });
    expect(clustered.nodes.some((n) => n.kind === "cluster")).toBe(false);
    expect(clustered.nodes).toHaveLength(graph.nodes.length);
    expect(clustered.edges).toHaveLength(graph.edges.length);
  });

  test("threshold is configurable", () => {
    const graph = fanOutGraph(3);
    const clustered = clusterLineage(graph, "art:1", { threshold: 2 });
    const cluster = clustered.nodes.find((n) => n.kind === "cluster");
    expect(cluster.count).toBe(2);
  });

  test("is deterministic", () => {
    const graph = fanOutGraph(8);
    const a = clusterLineage(graph, "art:1");
    const b = clusterLineage(graph, "art:1");
    expect(a.nodes.map((n) => n.id)).toEqual(b.nodes.map((n) => n.id));
    expect(a.edges).toEqual(b.edges);
  });
});
