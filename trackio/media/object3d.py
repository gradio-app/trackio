import json
import shutil
import struct
from pathlib import Path

import numpy as np

from trackio.media.media import TrackioMedia

SUPPORTED_FORMATS = frozenset({"glb", "gltf", "obj", "stl", "ply", "splat"})
MAX_POINT_COUNT = 300_000
_GLB_JSON_CHUNK = 0x4E4F534A
_CATEGORY_COLORS = np.asarray(
    [
        [31, 119, 180],
        [255, 127, 14],
        [44, 160, 44],
        [214, 39, 40],
        [148, 103, 189],
        [140, 86, 75],
        [227, 119, 194],
        [127, 127, 127],
        [188, 189, 34],
        [23, 190, 207],
        [57, 59, 121],
        [82, 84, 163],
        [107, 110, 207],
        [156, 158, 222],
    ],
    dtype=np.uint8,
)


def _gltf_document(path: Path) -> dict:
    if path.suffix.lower() == ".gltf":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid glTF file: {path}") from error
        if not isinstance(document, dict):
            raise ValueError(f"Invalid glTF file: {path}")
        return document

    try:
        data = path.read_bytes()
    except OSError:
        raise ValueError(f"Invalid GLB file: {path}") from None
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"Invalid GLB file: {path}")
    offset = 12
    while offset + 8 <= len(data):
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + length]
        offset += length
        if chunk_type == _GLB_JSON_CHUNK:
            try:
                document = json.loads(chunk.rstrip(b"\x00 \t\r\n").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"Invalid GLB file: {path}") from error
            if isinstance(document, dict):
                return document
            break
    raise ValueError(f"Invalid GLB file: {path}")


def _validate_self_contained(path: Path, file_format: str) -> None:
    if file_format in {"gltf", "glb"}:
        document = _gltf_document(path)
        references = []
        for key in ("buffers", "images"):
            collection = document.get(key, [])
            if not isinstance(collection, list):
                raise ValueError(f"Invalid glTF {key}: {path}")
            references.extend(
                item.get("uri") for item in collection if isinstance(item, dict)
            )
        if any(
            uri is not None
            and (not isinstance(uri, str) or not uri.startswith("data:"))
            for uri in references
        ):
            raise ValueError(
                "Object3D requires a self-contained glTF or GLB file; "
                "embed resources or convert the model to GLB"
            )
        return

    if file_format not in {"obj", "ply"}:
        return
    try:
        with path.open(encoding="utf-8", errors="replace") as file:
            for line in file:
                parts = line.split()
                if file_format == "obj" and parts and parts[0].lower() == "mtllib":
                    break
                if (
                    file_format == "ply"
                    and len(parts) >= 2
                    and parts[0].lower() == "comment"
                    and parts[1].lower() == "texturefile"
                ):
                    break
                if file_format == "ply" and parts == ["end_header"]:
                    return
            else:
                return
    except OSError as error:
        raise ValueError(f"Could not read 3D file: {path}") from error
    raise ValueError(
        f"Object3D requires a self-contained {file_format.upper()} file; "
        "external material and texture files are not supported"
    )


def _ply_header(path: Path) -> tuple[str, int | None, bool]:
    try:
        with path.open("rb") as file:
            header = file.read(256 * 1024)
    except OSError as error:
        raise ValueError(f"Could not read PLY file: {path}") from error
    end = header.find(b"end_header")
    if not header.startswith(b"ply") or end < 0:
        raise ValueError(f"Invalid PLY file: {path}")
    text = header[: end + len(b"end_header")].decode("ascii", errors="replace")
    vertex_properties = set()
    point_count = None
    has_faces = False
    current_element = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[:2] == ["element", "vertex"]:
            current_element = "vertex"
            try:
                point_count = int(parts[2])
                if point_count <= 0:
                    raise ValueError
            except ValueError as error:
                raise ValueError(f"Invalid PLY vertex count: {path}") from error
        elif len(parts) >= 3 and parts[:2] == ["element", "face"]:
            current_element = "face"
            try:
                has_faces = int(parts[2]) > 0
            except ValueError as error:
                raise ValueError(f"Invalid PLY face count: {path}") from error
        elif len(parts) >= 3 and parts[0] == "element":
            current_element = parts[1]
        elif len(parts) >= 3 and parts[0] == "property" and current_element == "vertex":
            vertex_properties.add(parts[-1])
    splat_fields = {
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
    }
    has_splat_color = {"f_dc_0", "f_dc_1", "f_dc_2"}.issubset(vertex_properties) or {
        "red",
        "green",
        "blue",
    }.issubset(vertex_properties)
    kind = (
        "gaussian_splat"
        if splat_fields.issubset(vertex_properties) and has_splat_color
        else "mesh"
        if has_faces
        else "point_cloud"
    )
    return kind, point_count, has_faces


def _write_point_cloud(path: Path, points: np.ndarray) -> None:
    positions = points[:, :3].astype("<f4", copy=False)
    categories = np.zeros(len(points), dtype=np.uint8)
    if points.shape[1] == 4:
        categories = points[:, 3].astype(np.uint8)
        colors = _CATEGORY_COLORS[categories - 1]
    elif points.shape[1] == 6:
        colors = points[:, 3:6].astype(np.uint8)
    else:
        colors = np.broadcast_to(
            np.array([148, 163, 184], dtype=np.uint8), (len(points), 3)
        )

    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(points)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "property uchar category\nend_header\n"
    ).encode("ascii")
    records = np.empty(
        len(points),
        dtype=[("position", "<f4", (3,)), ("color", "u1", (3,)), ("category", "u1")],
    )
    records["position"] = positions
    records["color"] = colors
    records["category"] = categories
    with path.open("wb") as file:
        file.write(header)
        file.write(records.tobytes())


class TrackioObject3D(TrackioMedia):
    TYPE = "trackio.object3d"

    def __init__(
        self, path_or_array: str | Path | np.ndarray, caption: str | None = None
    ):
        """Create a 3D object from a local model path or W&B-compatible point array."""
        if not isinstance(path_or_array, str | Path | np.ndarray):
            raise ValueError("Object3D requires a local file path or NumPy array")
        super().__init__(path_or_array, caption)
        self._format = (
            "ply"
            if isinstance(path_or_array, np.ndarray)
            else Path(path_or_array).suffix[1:].lower()
        )
        if self._format not in SUPPORTED_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_FORMATS))
            raise ValueError(
                f"Unsupported 3D format '{self._format}'. Supported formats: {supported}"
            )
        self._source_path: Path | None = None
        self.kind = "point_cloud" if isinstance(path_or_array, np.ndarray) else "mesh"
        self.original_point_count: int | None = None
        self.rendered_point_count: int | None = None

        if isinstance(path_or_array, np.ndarray):
            self._value = self._validate_array(path_or_array)
            self.original_point_count = len(path_or_array)
            if len(self._value) > MAX_POINT_COUNT:
                indices = np.linspace(
                    0, len(self._value) - 1, MAX_POINT_COUNT, dtype=np.int64
                )
                self._value = self._value[indices]
            self.rendered_point_count = len(self._value)
        else:
            self._source_path = Path(path_or_array).resolve()
            _validate_self_contained(self._source_path, self._format)
            if self._format == "ply":
                self.kind, self.original_point_count, _ = _ply_header(self._source_path)
                self.rendered_point_count = (
                    min(self.original_point_count, MAX_POINT_COUNT)
                    if self.kind == "point_cloud"
                    and self.original_point_count is not None
                    else self.original_point_count
                )
            elif self._format == "splat":
                self.kind = "gaussian_splat"

    @classmethod
    def from_file(cls, path: str | Path, caption: str | None = None):
        return cls(path, caption=caption)

    @classmethod
    def from_numpy(cls, array: np.ndarray, caption: str | None = None):
        return cls(array, caption=caption)

    @staticmethod
    def _validate_array(array: np.ndarray) -> np.ndarray:
        if array.ndim != 2 or array.shape[1] not in (3, 4, 6) or len(array) == 0:
            shape = getattr(array, "shape", None)
            raise ValueError(
                f"Object3D arrays must have shape (N, 3), (N, 4), or (N, 6), got {shape}"
            )
        if (
            not np.issubdtype(array.dtype, np.number)
            or np.issubdtype(array.dtype, np.complexfloating)
            or not np.isfinite(array).all()
            or np.abs(array[:, :3]).max() > np.finfo(np.float32).max
        ):
            raise ValueError("Object3D arrays must contain only finite numeric values")
        if array.shape[1] == 4:
            categories = array[:, 3]
            if (
                not np.equal(categories, np.floor(categories)).all()
                or not ((categories >= 1) & (categories <= 14)).all()
            ):
                raise ValueError(
                    "Object3D categories must be integers in the range [1, 14]"
                )
        if array.shape[1] == 6:
            colors = array[:, 3:6]
            if (
                not np.equal(colors, np.floor(colors)).all()
                or not ((colors >= 0) & (colors <= 255)).all()
            ):
                raise ValueError(
                    "Object3D RGB values must be integers in the range [0, 255]"
                )
        return np.asarray(array)

    def _save_media(self, file_path: Path):
        if isinstance(self._value, np.ndarray):
            _write_point_cloud(file_path, self._value)
        else:
            assert self._source_path
            shutil.copy2(self._source_path, file_path)

    def _to_dict(self) -> dict:
        value = super()._to_dict()
        value.update({"format": self._format, "kind": self.kind})
        if self.original_point_count is not None:
            value["original_point_count"] = self.original_point_count
        if self.rendered_point_count is not None:
            value["rendered_point_count"] = self.rendered_point_count
        return value
