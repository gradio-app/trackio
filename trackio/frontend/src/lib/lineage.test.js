import { describe, expect, test } from "vitest";
import golden from "./__fixtures__/lineage_golden.json";
import {
  buildLineage,
  buildRunOwnership,
  canonicalLinkRunId,
  sliceLineage,
} from "./lineage.js";

function goldenTables() {
  return {
    artifacts: golden.artifacts,
    versions: golden.artifact_versions.map((v) => ({
      ...v,
      manifest: JSON.stringify(v.manifest),
    })),
    aliases: golden.artifact_aliases,
    links: golden.run_artifact_links,
  };
}

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
    const result = buildLineage(
      tables,
      golden.runs,
      golden.focus_version_id,
    );
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
    const ownership = buildRunOwnership(
      [{ id: "id-1", name: "train" }],
      [],
    );
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

describe("sliceLineage", () => {
  const graph = buildLineage(
    goldenTables(),
    golden.runs,
    golden.focus_version_id,
  );

  test("depth window limits visible nodes", () => {
    const sliced = sliceLineage(graph, "art:3", { depth: 1 });
    expect(new Set(sliced.nodes.map((n) => n.id))).toEqual(
      new Set(["art:3", "run:train-b-1", "run:eval-1"]),
    );
    for (const edge of sliced.edges) {
      expect(sliced.nodes.some((n) => n.id === edge.source)).toBe(true);
      expect(sliced.nodes.some((n) => n.id === edge.target)).toBe(true);
    }
  });

  test("frontier reports hidden neighbor counts split by direction", () => {
    const sliced = sliceLineage(graph, "art:3", { depth: 1 });
    expect(sliced.frontier.get("run:train-b-1")).toEqual({
      upstream: 1,
      downstream: 0,
      total: 1,
    });
    expect(sliced.frontier.get("run:eval-1")).toEqual({
      upstream: 0,
      downstream: 1,
      total: 1,
    });
    expect(sliced.frontier.has("art:3")).toBe(false);
  });

  test("expansion reveals exactly one hop from the expanded node", () => {
    const sliced = sliceLineage(graph, "art:3", {
      depth: 1,
      expanded: new Map([["run:train-b-1", 20]]),
    });
    const ids = new Set(sliced.nodes.map((n) => n.id));
    expect(ids.has("art:1")).toBe(true);
    expect(ids.has("run:prep-1")).toBe(false);
    expect(ids.has("run:train-a-1")).toBe(false);
  });

  test("expansion cap reveals a batch and reports the remainder", () => {
    const sliced = sliceLineage(graph, "art:3", {
      depth: 0,
      expanded: new Map([["art:3", 1]]),
    });
    const ids = new Set(sliced.nodes.map((n) => n.id));
    expect(ids.size).toBe(2);
    expect(ids.has("run:train-b-1")).toBe(true);
    expect(sliced.frontier.get("art:3").total).toBe(1);
  });

  test("returns empty result when focus is missing", () => {
    expect(sliceLineage(graph, "art:999", {})).toEqual({
      nodes: [],
      edges: [],
      frontier: new Map(),
    });
  });

  test("is deterministic", () => {
    const a = sliceLineage(graph, "art:3", { depth: 2 });
    const b = sliceLineage(graph, "art:3", { depth: 2 });
    expect(a.nodes.map((n) => n.id)).toEqual(b.nodes.map((n) => n.id));
    expect(a.edges).toEqual(b.edges);
  });
});
