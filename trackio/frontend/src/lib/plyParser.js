const TYPE_READERS = {
  char: [1, "getInt8"],
  int8: [1, "getInt8"],
  uchar: [1, "getUint8"],
  uint8: [1, "getUint8"],
  short: [2, "getInt16"],
  int16: [2, "getInt16"],
  ushort: [2, "getUint16"],
  uint16: [2, "getUint16"],
  int: [4, "getInt32"],
  int32: [4, "getInt32"],
  uint: [4, "getUint32"],
  uint32: [4, "getUint32"],
  float: [4, "getFloat32"],
  float32: [4, "getFloat32"],
  double: [8, "getFloat64"],
  float64: [8, "getFloat64"],
};

function headerEnd(bytes) {
  const marker = new TextEncoder().encode("end_header");
  outer: for (let index = 0; index <= bytes.length - marker.length; index += 1) {
    for (let offset = 0; offset < marker.length; offset += 1) {
      if (bytes[index + offset] !== marker[offset]) continue outer;
    }
    let body = index + marker.length;
    if (bytes[body] === 13) body += 1;
    if (bytes[body] === 10) body += 1;
    return { header: index + marker.length, body };
  }
  throw new Error("PLY header is missing end_header");
}

function parseHeader(buffer) {
  const bytes = new Uint8Array(buffer);
  const end = headerEnd(bytes);
  const text = new TextDecoder("ascii").decode(bytes.subarray(0, end.header));
  const lines = text.split(/\r?\n/);
  if (lines[0]?.trim() !== "ply") throw new Error("Invalid PLY signature");
  const format = lines.find((line) => line.startsWith("format "))?.split(/\s+/)[1];
  if (!["ascii", "binary_little_endian", "binary_big_endian"].includes(format)) {
    throw new Error(`Unsupported PLY encoding: ${format || "unknown"}`);
  }
  const elements = [];
  let element = null;
  for (const line of lines) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === "element" && parts.length >= 3) {
      element = { name: parts[1], count: Number(parts[2]), properties: [] };
      if (!Number.isSafeInteger(element.count) || element.count < 0) {
        throw new Error(`Invalid PLY element count: ${parts[2]}`);
      }
      elements.push(element);
    } else if (parts[0] === "property" && element) {
      if (parts[1] === "list" && parts.length >= 5) {
        element.properties.push({
          name: parts[4],
          list: true,
          countType: parts[2],
          valueType: parts[3],
        });
      } else if (parts.length >= 3) {
        element.properties.push({ name: parts[2], type: parts[1] });
      }
    }
  }
  return { format, elements, bodyOffset: end.body };
}

function asciiReader(buffer, offset) {
  const body = new TextDecoder().decode(new Uint8Array(buffer, offset)).trim();
  const tokens = body ? body.split(/\s+/) : [];
  let cursor = 0;
  return () => {
    const value = Number(tokens[cursor]);
    cursor += 1;
    if (!Number.isFinite(value)) throw new Error("Invalid numeric value in ASCII PLY");
    return value;
  };
}

function binaryReader(buffer, offset, littleEndian) {
  const view = new DataView(buffer);
  let cursor = offset;
  return (type) => {
    const reader = TYPE_READERS[type];
    if (!reader) throw new Error(`Unsupported PLY property type: ${type}`);
    if (cursor + reader[0] > view.byteLength) throw new Error("Unexpected end of binary PLY");
    const value = view[reader[1]](cursor, littleEndian);
    cursor += reader[0];
    return value;
  };
}

function vertexValue(values, ...names) {
  for (const name of names) {
    if (values[name] !== undefined) return values[name];
  }
  return undefined;
}

export function parsePly(buffer, { maxPointCount = Infinity } = {}) {
  if (
    maxPointCount !== Infinity &&
    (!Number.isSafeInteger(maxPointCount) || maxPointCount < 1)
  ) {
    throw new Error(`Invalid PLY point limit: ${maxPointCount}`);
  }
  const header = parseHeader(buffer);
  const vertexElement = header.elements.find((element) => element.name === "vertex");
  const vertexProperties = vertexElement?.properties ?? [];
  const vertexPropertyNames = new Set(
    vertexProperties.map((property) => property.name),
  );
  const hasFaces = header.elements.some(
    (element) => element.name === "face" && element.count > 0,
  );
  const sampledPointCloud =
    !hasFaces && vertexElement && vertexElement.count > maxPointCount;
  const retainedPointCount = sampledPointCloud
    ? maxPointCount
    : (vertexElement?.count ?? 0);
  const sampleScale =
    retainedPointCount > 1
      ? (vertexElement.count - 1) / (retainedPointCount - 1)
      : 0;
  let retainedPointIndex = 0;
  const retainVertex = (index) => {
    if (!sampledPointCloud) return true;
    if (
      retainedPointIndex >= retainedPointCount ||
      index !== Math.floor(retainedPointIndex * sampleScale)
    ) {
      return false;
    }
    retainedPointIndex += 1;
    return true;
  };
  const hasNormalProperties = ["nx", "ny", "nz"].every((name) =>
    vertexPropertyNames.has(name),
  );
  const hasUvProperties =
    ["u", "s", "texture_u"].some((name) => vertexPropertyNames.has(name)) &&
    ["v", "t", "texture_v"].some((name) => vertexPropertyNames.has(name));
  const colorNames = new Set(["red", "green", "blue", "r", "g", "b"]);
  const colorProperties = vertexProperties.filter((property) =>
    colorNames.has(property.name),
  );
  const byteColors =
    colorProperties.length > 0 &&
    colorProperties.every((property) => ["uchar", "uint8"].includes(property.type));
  const read =
    header.format === "ascii"
      ? asciiReader(buffer, header.bodyOffset)
      : binaryReader(
          buffer,
          header.bodyOffset,
          header.format === "binary_little_endian",
        );
  const positions = [];
  const normals = [];
  const uvs = [];
  const colors = [];
  const indices = [];
  let hasNormals = false;
  let hasUvs = false;
  let hasColors = false;
  let colorMax = 0;

  for (const element of header.elements) {
    for (let index = 0; index < element.count; index += 1) {
      const values = {};
      for (const property of element.properties) {
        if (property.list) {
          const count = read(property.countType);
          if (!Number.isSafeInteger(count) || count < 0) {
            throw new Error(`Invalid PLY list length: ${count}`);
          }
          const list = new Array(count);
          for (let item = 0; item < count; item += 1) list[item] = read(property.valueType);
          values[property.name] = list;
        } else {
          values[property.name] = read(property.type);
        }
      }
      if (element.name === "vertex") {
        const x = values.x;
        const y = values.y;
        const z = values.z;
        if (![x, y, z].every(Number.isFinite)) throw new Error("PLY vertices require finite x, y, and z values");
        if (!retainVertex(index)) continue;
        positions.push(x, y, z);
        if (hasNormalProperties) {
          const nx = values.nx;
          const ny = values.ny;
          const nz = values.nz;
          if ([nx, ny, nz].every(Number.isFinite)) {
            normals.push(nx, ny, nz);
            hasNormals = true;
          } else normals.push(0, 0, 0);
        }
        if (hasUvProperties) {
          const u = vertexValue(values, "u", "s", "texture_u");
          const v = vertexValue(values, "v", "t", "texture_v");
          if ([u, v].every(Number.isFinite)) {
            uvs.push(u, v);
            hasUvs = true;
          } else uvs.push(0, 0);
        }
        if (colorProperties.length > 0) {
          const red = vertexValue(values, "red", "r");
          const green = vertexValue(values, "green", "g");
          const blue = vertexValue(values, "blue", "b");
          if ([red, green, blue].every(Number.isFinite)) {
            const alpha =
              vertexValue(values, "alpha", "a") ??
              (byteColors ? 255 : Math.max(red, green, blue) <= 1 ? 1 : 255);
            colors.push(red, green, blue, alpha);
            colorMax = Math.max(colorMax, red, green, blue, alpha);
            hasColors = true;
          } else colors.push(148, 163, 184, 255);
        }
      } else if (element.name === "face") {
        const face = values.vertex_indices ?? values.vertex_index;
        if (Array.isArray(face)) {
          for (let corner = 1; corner < face.length - 1; corner += 1) {
            indices.push(face[0], face[corner], face[corner + 1]);
          }
        }
      }
    }
  }
  if (!positions.length) throw new Error("PLY contains no vertices");
  const vertexCount = positions.length / 3;
  for (const index of indices) {
    if (!Number.isSafeInteger(index) || index < 0 || index >= vertexCount) {
      throw new Error(`PLY face references invalid vertex index: ${index}`);
    }
  }
  const colorScale = !byteColors && colorMax <= 1 ? 255 : 1;
  return {
    topology: indices.length ? "triangle-list" : "point-list",
    originalVertexCount: vertexElement?.count ?? vertexCount,
    attributes: {
      POSITION: { value: new Float32Array(positions), size: 3 },
      ...(hasNormals ? { NORMAL: { value: new Float32Array(normals), size: 3 } } : {}),
      ...(hasUvs ? { TEXCOORD_0: { value: new Float32Array(uvs), size: 2 } } : {}),
      ...(hasColors
        ? {
            COLOR_0: {
              value: new Uint8Array(colors.map((value) => Math.round(value * colorScale))),
              size: 4,
              normalized: true,
            },
          }
        : {}),
    },
    indices: indices.length ? { value: new Uint32Array(indices), size: 1 } : null,
  };
}
