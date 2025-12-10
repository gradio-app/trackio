import os
import shutil
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

try:
    from trackio.media.media import TrackioMedia
except ImportError:
    from media.media import TrackioMedia


TrackioImageSourceType = str | Path | np.ndarray | PILImage.Image


class TrackioImage(TrackioMedia):
    """
    Initializes an Image object.

    Example:
        ```python
        import trackio
        import numpy as np
        from PIL import Image

        # Create an image from numpy array
        image_data = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        image = trackio.Image(image_data, caption="Random image")
        trackio.log({"my_image": image})

        # Create an image from PIL Image
        pil_image = Image.new('RGB', (100, 100), color='red')
        image = trackio.Image(pil_image, caption="Red square")
        trackio.log({"red_image": image})

        # Create an image from file path
        image = trackio.Image("path/to/image.jpg", caption="Photo from file")
        trackio.log({"file_image": image})
        ```

    Args:
        value (`str`, `Path`, `numpy.ndarray`, or `PIL.Image`, *optional*):
            A path to an image, a PIL Image, or a numpy array of shape (height, width, channels).
            If numpy array, should be of type `np.uint8` with RGB values in the range `[0, 255]`.
        caption (`str`, *optional*):
            A string caption for the image.
    """

    TYPE = "trackio.image"

    def __init__(self, value: TrackioImageSourceType, caption: str | None = None):
        super().__init__(value, caption)
        self._format: str | None = None

        if not isinstance(self._value, TrackioImageSourceType):
            raise ValueError(
                f"Invalid value type, expected {TrackioImageSourceType}, got {type(self._value)}"
            )
        if isinstance(self._value, np.ndarray) and self._value.dtype != np.uint8:
            raise ValueError(
                f"Invalid value dtype, expected np.uint8, got {self._value.dtype}"
            )
        if (
            isinstance(self._value, np.ndarray | PILImage.Image)
            and self._format is None
        ):
            self._format = "png"

    def _as_pil(self) -> PILImage.Image | None:
        try:
            if isinstance(self._value, np.ndarray):
                arr = np.asarray(self._value).astype("uint8")
                return PILImage.fromarray(arr).convert("RGBA")
            if isinstance(self._value, PILImage.Image):
                return self._value.convert("RGBA")
        except Exception as e:
            raise ValueError(f"Failed to process image data: {self._value}") from e
        return None

    def _save_media(self, file_path: Path):
        if pil := self._as_pil():
            pil.save(file_path, format=self._format)
        elif isinstance(self._value, str | Path):
            if os.path.isfile(self._value):
                shutil.copy(self._value, file_path)
            else:
                raise ValueError(f"File not found: {self._value}")
