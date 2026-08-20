import json
from pathlib import Path

import numpy as np
import pytest

import trackio
from trackio.media.object3d import MAX_POINT_COUNT, _ply_header
from trackio.sqlite_storage import SQLiteStorage


@pytest.mark.parametrize("width", [3, 4, 6])
def test_object3d_accepts_supported_numpy_shapes(width):
    points = np.zeros((4, width), dtype=np.float32)
    if width == 4:
        points[:, 3] = [1, 2, 13, 14]
    object3d = trackio.Object3D.from_numpy(points)

    assert object3d.kind == "point_cloud"
    assert object3d.original_point_count == 4
    assert object3d.rendered_point_count == 4


@pytest.mark.parametrize(
    "points, message",
    [
        (np.zeros((2, 2)), "shape"),
        (np.zeros((0, 3)), "shape"),
        (np.array([[np.inf, 0, 0]]), "finite"),
        (np.array([[0, 0, 0, 0]]), "categories"),
        (np.array([[0, 0, 0, 0, 0, 256]]), "RGB"),
    ],
)
def test_object3d_rejects_invalid_numpy_values(points, message):
    with pytest.raises(ValueError, match=message):
        trackio.Object3D(points)


def test_object3d_rejects_invalid_inputs(tmp_path):
    unsupported = tmp_path / "model.fbx"
    unsupported.write_bytes(b"model")

    with pytest.raises(ValueError, match="Unsupported 3D format"):
        trackio.Object3D(unsupported)
    with pytest.raises(ValueError, match="File not found"):
        trackio.Object3D(tmp_path / "missing.glb")
    with pytest.raises(ValueError, match="local file path or NumPy array"):
        trackio.Object3D([1, 2, 3])


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("scene.gltf", json.dumps({"buffers": [{"uri": "mesh.bin"}]})),
        ("scene.obj", "mtllib material.mtl\nv 0 0 0\n"),
        (
            "scene.ply",
            "ply\nformat ascii 1.0\ncomment TextureFile texture.png\nend_header\n",
        ),
    ],
)
def test_object3d_rejects_external_resources(tmp_path, name, content):
    source = tmp_path / name
    source.write_text(content)

    with pytest.raises(ValueError, match="self-contained"):
        trackio.Object3D(source)


def test_object3d_accepts_embedded_gltf_resources(tmp_path):
    source = tmp_path / "scene.gltf"
    source.write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "buffers": [
                    {
                        "uri": "data:application/octet-stream;base64,AAAA",
                        "byteLength": 3,
                    }
                ],
            }
        )
    )

    assert trackio.Object3D(source).kind == "mesh"


@pytest.mark.parametrize(
    "properties, faces, expected",
    [
        ("property float x\nproperty float y\nproperty float z\n", 0, "point_cloud"),
        ("property float x\nproperty float y\nproperty float z\n", 1, "mesh"),
        (
            "property float x\nproperty float y\nproperty float z\n"
            "property float opacity\nproperty float scale_0\nproperty float scale_1\n"
            "property float scale_2\nproperty float rot_0\nproperty float rot_1\n"
            "property float rot_2\nproperty float rot_3\nproperty float f_dc_0\n"
            "property float f_dc_1\nproperty float f_dc_2\n",
            0,
            "gaussian_splat",
        ),
    ],
)
def test_ply_classification(tmp_path, properties, faces, expected):
    source = tmp_path / "model.ply"
    source.write_text(
        "ply\nformat ascii 1.0\nelement vertex 2\n"
        f"{properties}element face {faces}\nproperty list uchar int vertex_indices\n"
        "end_header\n0 0 0\n1 1 1\n"
    )

    kind, count, has_faces = _ply_header(source)

    assert (kind, count, has_faces) == (expected, 2, bool(faces))


def test_object3d_samples_point_cloud_deterministically():
    points = np.arange((MAX_POINT_COUNT + 2) * 3, dtype=np.float32).reshape(-1, 3)
    first = trackio.Object3D(points)
    second = trackio.Object3D(points.copy())

    assert first.rendered_point_count == MAX_POINT_COUNT
    np.testing.assert_array_equal(first._value, second._value)
    np.testing.assert_array_equal(first._value[[0, -1]], points[[0, -1]])


def test_object3d_numpy_serializes_to_binary_ply(temp_dir):
    object3d = trackio.Object3D(np.array([[1, 2, 3, 4]], dtype=np.float32))
    object3d._save("project", "run", 7)
    descriptor = object3d._to_dict()

    assert descriptor == {
        "_type": "trackio.object3d",
        "file_path": str(Path("project/run/7") / Path(descriptor["file_path"]).name),
        "caption": None,
        "format": "ply",
        "kind": "point_cloud",
        "original_point_count": 1,
        "rendered_point_count": 1,
    }
    data = object3d._get_absolute_file_path().read_bytes()
    assert b"property uchar category" in data
    assert data[-4:] == bytes([214, 39, 40, 4])


def test_object3d_file_is_copied_verbatim(tmp_path, temp_dir):
    source = tmp_path / "model.stl"
    source.write_text("solid model\nendsolid model\n")
    object3d = trackio.Object3D.from_file(source)
    object3d._save("project", "run", 3)
    relative = object3d._get_relative_file_path()

    assert relative.parent == Path("project/run/3")
    assert relative.suffix == ".stl"
    assert object3d._get_absolute_file_path().read_text() == source.read_text()


def test_object3d_logs_directly_and_inside_tables(temp_dir):
    run = trackio.init(project="project", name="run")
    run.log(
        {
            "model": trackio.Object3D(np.array([[0, 0, 0]], dtype=np.float32)),
            "samples": trackio.Table(
                columns=["model"],
                data=[[trackio.Object3D(np.array([[1, 1, 1]], dtype=np.float32))]],
            ),
        }
    )
    run.finish()
    log = SQLiteStorage.get_logs("project", "run")[0]
    direct_value = log["model"]
    nested_value = log["samples"]["_value"][0]["model"]

    assert direct_value["_type"] == "trackio.object3d"
    assert nested_value["_type"] == "trackio.object3d"
    assert (Path(temp_dir) / "media" / direct_value["file_path"]).is_file()
    assert (Path(temp_dir) / "media" / nested_value["file_path"]).is_file()
    assert SQLiteStorage.get_tab_availability_flags("project")["media"] is True
