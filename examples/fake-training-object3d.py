import json
import math
import random
import struct
import time
from pathlib import Path

import numpy as np

import trackio

EPOCHS = 8
OUTPUT_DIR = Path(__file__).parent / "files" / "object3d"


def sphere_point_cloud(count, noise):
    rng = np.random.default_rng(0)
    phi = rng.uniform(0, 2 * math.pi, count)
    costheta = rng.uniform(-1, 1, count)
    theta = np.arccos(costheta)
    radius = 1.0 + rng.normal(0, noise, count)
    points = np.stack(
        [
            radius * np.sin(theta) * np.cos(phi),
            radius * np.sin(theta) * np.sin(phi),
            radius * np.cos(theta),
        ],
        axis=1,
    )
    colors = np.clip((points + 1.5) / 3.0 * 255, 0, 255).astype(np.int64)
    return np.concatenate([points, colors], axis=1)


def categorized_point_cloud(count):
    rng = np.random.default_rng(1)
    centers = np.array([[-1.2, 0, 0], [1.2, 0, 0], [0, 1.6, 0]])
    categories = rng.integers(1, 4, count)
    points = centers[categories - 1] + rng.normal(0, 0.22, (count, 3))
    return np.concatenate([points, categories[:, None]], axis=1)


def write_ascii_ply_mesh(path):
    vertices = [
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (0, 3, 7, 4),
        (1, 2, 6, 5),
    ]
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(vertices)}",
        "property float x",
        "property float y",
        "property float z",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        f"element face {len(faces)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    for index, (x, y, z) in enumerate(vertices):
        color = [(index * 37) % 256, (index * 91) % 256, (index * 143) % 256]
        lines.append(f"{x} {y} {z} {color[0]} {color[1]} {color[2]}")
    for face in faces:
        lines.append(f"{len(face)} " + " ".join(str(i) for i in face))
    path.write_text("\n".join(lines) + "\n")
    return path


def write_stl_pyramid(path):
    apex = (0.0, 0.0, 1.6)
    base = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
    triangles = [(apex, base[i], base[(i + 1) % 4]) for i in range(4)]
    triangles += [(base[0], base[1], base[2]), (base[0], base[2], base[3])]
    lines = ["solid pyramid"]
    for triangle in triangles:
        lines.append("facet normal 0 0 0")
        lines.append("  outer loop")
        for vertex in triangle:
            lines.append("    vertex {} {} {}".format(*vertex))
        lines.append("  endloop")
        lines.append("endfacet")
    lines.append("endsolid pyramid")
    path.write_text("\n".join(lines) + "\n")
    return path


def write_obj_tetrahedron(path):
    vertices = [(0, 0, 1.4), (-1, -0.6, 0), (1, -0.6, 0), (0, 1.2, 0)]
    faces = [(1, 2, 3), (1, 3, 4), (1, 4, 2), (2, 4, 3)]
    lines = ["# tetrahedron with no external material library"]
    lines += ["v {} {} {}".format(*vertex) for vertex in vertices]
    lines += ["f {} {} {}".format(*face) for face in faces]
    path.write_text("\n".join(lines) + "\n")
    return path


def write_glb_triangle(path):
    positions = [(0.0, 0.0, 0.0), (1.5, 0.0, 0.0), (0.0, 1.5, 0.0)]
    vertex_bytes = b"".join(struct.pack("<3f", *position) for position in positions)
    index_bytes = struct.pack("<3H", 0, 1, 2)
    padding = b"\x00" * ((4 - len(index_bytes) % 4) % 4)
    blob = index_bytes + padding + vertex_bytes
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(index_bytes)},
            {
                "buffer": 0,
                "byteOffset": len(index_bytes) + len(padding),
                "byteLength": len(vertex_bytes),
            },
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5123, "count": 3, "type": "SCALAR"},
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [1.5, 1.5, 0.0],
            },
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode()
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary_chunk = blob + b"\x00" * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    glb = struct.pack("<4sII", b"glTF", 2, total)
    glb += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    glb += struct.pack("<II", len(binary_chunk), 0x004E4942) + binary_chunk
    path.write_bytes(glb)
    return path


def build_assets():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "glb": write_glb_triangle(OUTPUT_DIR / "triangle.glb"),
        "obj": write_obj_tetrahedron(OUTPUT_DIR / "tetrahedron.obj"),
        "stl": write_stl_pyramid(OUTPUT_DIR / "pyramid.stl"),
        "ply": write_ascii_ply_mesh(OUTPUT_DIR / "cube.ply"),
    }


def main():
    assets = build_assets()
    project_name = f"object3d-demo-{random.randint(10000, 99999)}"
    trackio.init(project=project_name, name="reconstruction")

    trackio.log(
        {
            "mesh_glb": trackio.Object3D(assets["glb"], caption="GLB triangle"),
            "mesh_obj": trackio.Object3D(assets["obj"], caption="OBJ tetrahedron"),
            "mesh_stl": trackio.Object3D(assets["stl"], caption="STL pyramid"),
            "mesh_ply": trackio.Object3D(assets["ply"], caption="ASCII PLY cube"),
            "segmentation": trackio.Object3D(
                categorized_point_cloud(4000), caption="Categories 1-3"
            ),
        }
    )

    for epoch in range(EPOCHS):
        noise = 0.45 * (1.0 - epoch / (EPOCHS - 1))
        cloud = sphere_point_cloud(20_000, noise)
        table = trackio.Table(
            columns=["sample", "reconstruction"],
            data=[
                [f"sphere-{epoch}", trackio.Object3D(cloud, caption=f"epoch {epoch}")]
            ],
        )
        trackio.log(
            {
                "chamfer_distance": noise,
                "reconstruction": trackio.Object3D(
                    cloud, caption=f"epoch {epoch} (noise={noise:.3f})"
                ),
                "reconstructions": table,
            },
            step=epoch,
        )
        time.sleep(0.2)

    trackio.log(
        {"large_cloud": trackio.Object3D(sphere_point_cloud(400_000, 0.02))},
        step=EPOCHS,
    )

    trackio.finish()
    print(f'Run: trackio show --project "{project_name}"')


if __name__ == "__main__":
    main()
