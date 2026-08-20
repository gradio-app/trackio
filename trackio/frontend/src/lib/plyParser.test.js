import { describe, expect, it } from "vitest";
import { parsePly } from "./plyParser.js";

function asciiBuffer(text) {
  return new TextEncoder().encode(text).buffer;
}

describe("parsePly", () => {
  it("parses ASCII point clouds with colors", () => {
    const result = parsePly(
      asciiBuffer(
        "ply\nformat ascii 1.0\nelement vertex 2\n" +
          "property float x\nproperty float y\nproperty float z\n" +
          "property uchar red\nproperty uchar green\nproperty uchar blue\n" +
          "end_header\n0 1 2 255 0 16\n3 4 5 0 128 255\n",
      ),
    );

    expect(result.topology).toBe("point-list");
    expect([...result.attributes.POSITION.value]).toEqual([0, 1, 2, 3, 4, 5]);
    expect([...result.attributes.COLOR_0.value]).toEqual([
      255, 0, 16, 255, 0, 128, 255, 255,
    ]);
  });

  it("triangulates ASCII polygon faces", () => {
    const result = parsePly(
      asciiBuffer(
        "ply\nformat ascii 1.0\nelement vertex 4\n" +
          "property float x\nproperty float y\nproperty float z\n" +
          "element face 1\nproperty list uchar int vertex_indices\nend_header\n" +
          "0 0 0\n1 0 0\n1 1 0\n0 1 0\n4 0 1 2 3\n",
      ),
      { maxPointCount: 2 },
    );

    expect(result.topology).toBe("triangle-list");
    expect(result.attributes.POSITION.value).toHaveLength(12);
    expect([...result.indices.value]).toEqual([0, 1, 2, 0, 2, 3]);
  });

  it("parses binary little-endian vertices", () => {
    const header = new TextEncoder().encode(
      "ply\nformat binary_little_endian 1.0\nelement vertex 1\n" +
        "property float x\nproperty float y\nproperty float z\nend_header\n",
    );
    const buffer = new ArrayBuffer(header.length + 12);
    new Uint8Array(buffer).set(header);
    const view = new DataView(buffer);
    view.setFloat32(header.length, 1.25, true);
    view.setFloat32(header.length + 4, -2.5, true);
    view.setFloat32(header.length + 8, 3.75, true);

    const result = parsePly(buffer);

    expect([...result.attributes.POSITION.value]).toEqual([1.25, -2.5, 3.75]);
  });

  it("samples point attributes while parsing", () => {
    const result = parsePly(
      asciiBuffer(
        "ply\nformat ascii 1.0\nelement vertex 6\n" +
          "property float x\nproperty float y\nproperty float z\n" +
          "property uchar red\nproperty uchar green\nproperty uchar blue\n" +
          "end_header\n" +
          "0 0 0 0 0 0\n1 0 0 1 0 0\n2 0 0 2 0 0\n" +
          "3 0 0 3 0 0\n4 0 0 4 0 0\n5 0 0 5 0 0\n",
      ),
      { maxPointCount: 3 },
    );

    expect(result.originalVertexCount).toBe(6);
    expect([...result.attributes.POSITION.value]).toEqual([
      0, 0, 0, 2, 0, 0, 5, 0, 0,
    ]);
    expect([...result.attributes.COLOR_0.value]).toEqual([
      0, 0, 0, 255, 2, 0, 0, 255, 5, 0, 0, 255,
    ]);
  });

  it("rejects malformed files", () => {
    expect(() => parsePly(asciiBuffer("not-ply"))).toThrow("end_header");
    expect(() =>
      parsePly(
        asciiBuffer(
          "ply\nformat ascii 1.0\nelement vertex 1\n" +
            "property float x\nproperty float y\nproperty float z\nend_header\n0 nope 1\n",
        ),
      ),
    ).toThrow("Invalid numeric value");
  });
});
