import io
from pathlib import Path
import uuid
import numpy as np
from PIL import Image as PILImage, UnidentifiedImageError
from typing import Union, Optional

try: # absolute imports when installed
    from trackio.utils import TRACKIO_DIR
    from trackio.file_storage import FileStorage
except ImportError: # relative imports for local execution on Spaces
    from utils import TRACKIO_DIR
    from file_storage import FileStorage

class TrackioImage:
	TYPE = "trackio.image"

	def __init__(self, value: Union[str, np.ndarray, PILImage.Image], caption: Optional[str] = None):
		self.caption = caption
		self._pil = self._convert_to_pil(value)
		self._file_path: Path | None = None

	def _convert_to_pil(self, value: Union[str, np.ndarray, PILImage.Image]) -> PILImage.Image:
		try:
			if isinstance(value, str):
				return self._from_path(value)
			elif isinstance(value, np.ndarray):
				return self._from_array(value)
			elif isinstance(value, PILImage.Image):
				return value.convert("RGBA")
			else:
				raise ValueError(f"Unsupported image type: {type(value)}")
		except Exception as e:
			raise ValueError(f"Failed to process image data: {value}") from e

	def _from_array(self, arr: np.ndarray) -> PILImage.Image:
		arr = np.asarray(arr).astype("uint8")
		if arr.ndim == 2:
				return PILImage.fromarray(arr, mode="L")
		elif arr.ndim == 3:
			if arr.shape[2] == 3:
				return PILImage.fromarray(arr, mode="RGB").convert("RGBA")
			if arr.shape[2] == 4:
				return PILImage.fromarray(arr, mode="RGBA")
		raise ValueError("Unsupported array shape. Expect (H,W), (H,W,3), or (H,W,4)")

	def _from_path(self, path: str) -> PILImage.Image:
		try:
			return PILImage.open(path).convert("RGBA")
		except FileNotFoundError as e:
			raise ValueError(f"Image file not found: {path}") from e 
		except UnidentifiedImageError as e:
			raise ValueError(f"File is not a valid image: {path}") from e
	
	def to_bytes(self, format: str = "PNG") -> bytes:
		buffer = io.BytesIO()
		self._pil.save(buffer, format=format)
		return buffer.getvalue()
	
	def save_to_file(self, project: str, run: str, step: int = 0, format: str = "PNG") -> str:
		# Save under: {TRACKIO_DIR}/media/{project}/{run}/{step}/{uuid}.{ext}
		filename = f"{uuid.uuid4()}.{format.lower()}"
		path = FileStorage.save_image(self._pil, project, run, step, filename, format=format)
		self._file_path = path
		return str(self._file_path)
	
	def get_relative_file_path(self) -> Path | None:
		return self._file_path.relative_to(TRACKIO_DIR)
	
	def get_absolute_file_path(self) -> Path | None:
		return self._file_path
	
	def to_json(self) -> dict:
		if not self._file_path:
			raise ValueError("Image must be saved to file before serialization")
		return {
			"_type": self.TYPE,
			"file_path": str(self.get_relative_file_path()),
			"format": "PNG",
			"caption": self.caption,
		}

	@classmethod
	def from_json(cls, obj: dict) -> "TrackioImage":
		if not isinstance(obj, dict):
			raise TypeError(f"Expected dict, got {type(obj).__name__}")
		if obj.get("_type") != cls.TYPE:
			raise ValueError(f"Wrong _type: {obj.get('_type')!r}")
		
		file_path = obj.get("file_path")
		if not isinstance(file_path, str):
			raise TypeError(f"'file_path' must be string, got {type(file_path).__name__}")
		
		try:
			absolute_path = TRACKIO_DIR / file_path
			if not absolute_path.exists():
				raise ValueError(f"Image file not found: {file_path}")
			pil = PILImage.open(absolute_path).convert("RGBA")
			instance = cls(pil, caption=obj.get("caption"))
			instance._file_path = Path(file_path)
			return instance
		except Exception as e:
			raise ValueError(f"Failed to load image from file: {file_path}") from e
