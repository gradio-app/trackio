import json
import struct
from pathlib import Path

import numpy as np
import pytest

import trackio
from trackio.media.object3d import MAX_POINT_COUNT, TrackioObject3D, _ply_header
from trackio.run import Run
from trackio.sqlite_storage import SQLiteStorage


@pytest.mark.parametrize("width", [3, 4, 6])
def test_object3d_accepts_supported_numpy_shapes(width):
    points = np.zeros((4, width), dtype=np.float32)
    if width == 4:
        points[:, 3] = [1, 2, 13, 14]
    object3d = trackio.Object3D.from_numpy(points)

    assert isinstance(object3d, TrackioObject3D)
    assert object3d.original_point_count == 4
    assert object3d.rendered_point_count == 4


def test_object3d_accepts_public_path_or_array_keyword():
    object3d = trackio.Object3D(path_or_array=np.zeros((1, 3)))

    assert object3d.kind == "point_cloud"
    assert "Object3D" in trackio.__all__


def test_object3d_accepts_glb_and_splat_files(tmp_path):
    document = b'{"asset":{"version":"2.0"}}'
    document += b" " * (-len(document) % 4)
    glb = tmp_path / "scene.glb"
    glb.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(document))
        + struct.pack("<II", len(document), 0x4E4F534A)
        + document
    )
    splat = tmp_path / "scene.splat"
    splat.write_bytes(b"splat")

    assert trackio.Object3D(glb)._format == "glb"
    assert trackio.Object3D(splat).kind == "gaussian_splat"


@pytest.mark.parametrize(
    ("suffix", "content", "message"),
    [
        (".gltf", "[]", "Invalid glTF file"),
        (".glb", b"not a glb", "Invalid GLB file"),
    ],
)
def test_object3d_rejects_malformed_gltf_files(tmp_path, suffix, content, message):
    path = tmp_path / f"scene{suffix}"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)

    with pytest.raises(ValueError, match=message):
        trackio.Object3D(path)


@pytest.mark.parametrize(
    "points, message",
    [
        (np.zeros((2, 2)), "shape"),
        (np.zeros((0, 3)), "shape"),
        (np.array([[np.inf, 0, 0]]), "finite"),
        (np.array([[1 + 2j, 0, 0]]), "finite"),
        (np.array([[0, 0, 0, 0]]), "categories"),
        (np.array([[0, 0, 0, 1.5]]), "categories"),
        (np.array([[0, 0, 0, 0, 0, 256]]), "RGB"),
        (np.array([[0, 0, 0, 0, 0, 1.5]]), "RGB"),
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


def test_object3d_samples_point_cloud_deterministically():
    points = np.arange((MAX_POINT_COUNT + 2) * 3, dtype=np.float32).reshape(-1, 3)
    first = trackio.Object3D(points)
    second = trackio.Object3D(points.copy())

    assert first.rendered_point_count == MAX_POINT_COUNT
    np.testing.assert_array_equal(first._value, second._value)
    np.testing.assert_array_equal(first._value[[0, -1]], points[[0, -1]])


def test_object3d_numpy_uses_single_file_layout(temp_dir):
    object3d = trackio.Object3D(np.array([[1, 2, 3, 4]], dtype=np.float32))
    object3d._save("project", "run", 7)
    descriptor = object3d._to_dict()
    relative = Path(descriptor["file_path"])

    assert relative.parent == Path("project/run/7")
    assert relative.suffix == ".ply"
    assert "asset_paths" not in descriptor
    assert descriptor == {
        "_type": "trackio.object3d",
        "file_path": str(relative),
        "caption": None,
        "format": "ply",
        "kind": "point_cloud",
        "original_point_count": 1,
        "rendered_point_count": 1,
    }
    assert object3d._get_absolute_file_path().is_file()
    data = object3d._get_absolute_file_path().read_bytes()
    assert b"property uchar category" in data
    assert data[-4:] == bytes([214, 39, 40, 4])


def test_object3d_single_file_model_uses_existing_layout(tmp_path, temp_dir):
    source = tmp_path / "model.stl"
    source.write_text("solid model\nendsolid model\n")
    object3d = trackio.Object3D.from_file(source)
    object3d._save("project", "run", 3)
    relative = object3d._get_relative_file_path()

    assert relative.parent == Path("project/run/3")
    assert relative.suffix == ".stl"
    assert object3d._get_absolute_file_path().read_text() == source.read_text()


def test_object3d_embedded_gltf_uses_single_file_layout(tmp_path, temp_dir):
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
    object3d = trackio.Object3D(source, caption="scene")
    object3d._save("project", "run", 2)
    descriptor = object3d._to_dict()
    primary = Path(descriptor["file_path"])

    assert primary.parent == Path("project/run/2")
    assert primary.suffix == ".gltf"
    assert "asset_paths" not in descriptor
    assert (Path(temp_dir) / "media" / primary).read_text() == source.read_text()


@pytest.mark.parametrize(
    "uri",
    [
        "../mesh.bin",
        "..\\mesh.bin",
        "/tmp/mesh.bin",
        "https://example.com/mesh.bin",
    ],
)
def test_object3d_rejects_external_gltf_resources(tmp_path, uri):
    source = tmp_path / "scene.gltf"
    source.write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "buffers": [{"uri": uri, "byteLength": 4}],
            }
        )
    )

    with pytest.raises(ValueError, match="self-contained"):
        trackio.Object3D(source)


@pytest.mark.parametrize(
    ("suffix", "content"),
    [
        ("obj", "mtllib material.mtl\nv 0 0 0\n"),
        (
            "ply",
            "ply\nformat ascii 1.0\ncomment TextureFile texture.png\nend_header\n",
        ),
    ],
)
def test_object3d_rejects_external_materials_and_textures(tmp_path, suffix, content):
    source = tmp_path / f"scene.{suffix}"
    source.write_text(content)

    with pytest.raises(ValueError, match="self-contained"):
        trackio.Object3D(source)


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

    assert kind == expected
    assert count == 2
    assert has_faces is bool(faces)


def test_object3d_logs_directly_and_inside_tables(temp_dir):
    run = trackio.init(project="project", name="run")
    direct = trackio.Object3D(np.array([[0, 0, 0]], dtype=np.float32))
    nested = trackio.Object3D(np.array([[1, 1, 1]], dtype=np.float32))

    run.log(
        {
            "model": direct,
            "samples": trackio.Table(columns=["model"], data=[[nested]]),
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


def test_object3d_enables_media_tab(temp_dir):
    run = trackio.init(project="project", name="run")
    run.log({"model": trackio.Object3D(np.array([[0, 0, 0]]))})
    run.finish()

    flags = SQLiteStorage.get_tab_availability_flags("project")

    assert flags["media"] is True


def test_object3d_upload_uses_standard_single_file_path(
    tmp_path, temp_dir, monkeypatch
):
    source = tmp_path / "scene.stl"
    source.write_text("solid model\nendsolid model\n")
    run = Run(url=None, project="project", client=None, name="run", space_id=None)
    run._space_id = "owner/space"
    uploads = []
    monkeypatch.setattr(
        run,
        "_queue_upload",
        lambda path, step, relative_path=None: uploads.append((Path(path), step)),
    )

    descriptor = run._process_media(trackio.Object3D(source), 5)

    assert Path(descriptor["file_path"]).parent == Path("project/run/5")
    assert uploads == [(Path(temp_dir) / "media" / descriptor["file_path"], 5)]
