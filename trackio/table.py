import os
from typing import Any, Literal

from pandas import DataFrame

try:
    from trackio.media.media import TrackioMedia
    from trackio.utils import MEDIA_DIR
except ImportError:
    from media.media import TrackioMedia
    from utils import MEDIA_DIR


class Table:
    """
    Initializes a Table object.

    Tables can be used to log tabular data including images, numbers, and text.

    Args:
        columns (`list[str]`, *optional*):
            Names of the columns in the table. Optional if `data` is provided. Not
            expected if `dataframe` is provided. Currently ignored.
        data (`list[list[Any]]`, *optional*):
            2D row-oriented array of values. Each value can be a number, a string
            (treated as Markdown and truncated if too long), or a `Trackio.Image` or
            list of `Trackio.Image` objects.
        dataframe (`pandas.DataFrame`, *optional*):
            DataFrame used to create the table. When set, `data` and `columns`
            arguments are ignored.
        rows (`list[list[Any]]`, *optional*):
            Currently ignored.
        optional (`bool` or `list[bool]`, *optional*, defaults to `True`):
            Currently ignored.
        allow_mixed_types (`bool`, *optional*, defaults to `False`):
            Currently ignored.
        log_mode: (`Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"]` or `None`, *optional*, defaults to `"IMMUTABLE"`):
            Currently ignored.
    """

    TYPE = "trackio.table"

    def __init__(
        self,
        columns: list[str] | None = None,
        data: list[list[Any]] | None = None,
        dataframe: DataFrame | None = None,
        rows: list[list[Any]] | None = None,
        optional: bool | list[bool] = True,
        allow_mixed_types: bool = False,
        log_mode: Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"] | None = "IMMUTABLE",
    ):
        # TODO: implement support for columns, dtype, optional, allow_mixed_types, and log_mode.
        # for now (like `rows`) they are included for API compat but don't do anything.
        if dataframe is None:
            self.data = DataFrame(data) if data is not None else DataFrame()
        else:
            self.data = dataframe

    def _has_media_objects(self, dataframe: DataFrame) -> bool:
        """Check if dataframe contains any TrackioMedia objects or lists of TrackioMedia objects."""
        for col in dataframe.columns:
            if dataframe[col].apply(lambda x: isinstance(x, TrackioMedia)).any():
                return True
            if (
                dataframe[col]
                .apply(
                    lambda x: isinstance(x, list)
                    and len(x) > 0
                    and isinstance(x[0], TrackioMedia)
                )
                .any()
            ):
                return True
        return False

    def _process_data(self, project: str, run: str, step: int = 0):
        """Convert dataframe to dict format, processing any TrackioMedia objects if present."""
        df = self.data
        if not self._has_media_objects(df):
            return df.to_dict(orient="records")

        processed_df = df.copy()
        for col in processed_df.columns:
            for idx in processed_df.index:
                value = processed_df.at[idx, col]
                if isinstance(value, TrackioMedia):
                    value._save(project, run, step)
                    processed_df.at[idx, col] = value._to_dict()
                if (
                    isinstance(value, list)
                    and len(value) > 0
                    and isinstance(value[0], TrackioMedia)
                ):
                    [v._save(project, run, step) for v in value]
                    processed_df.at[idx, col] = [v._to_dict() for v in value]

        return processed_df.to_dict(orient="records")

    @staticmethod
    def to_display_format(table_data: list[dict]) -> list[dict]:
        """
        Converts stored table data to display format for UI rendering.

        Note:
            This does not use the `self.data` attribute, but instead uses the
            `table_data` parameter, which is what the UI receives.

        Args:
            table_data (`list[dict]`):
                List of dictionaries representing table rows (from stored `_value`).

        Returns:
            `list[dict]`: Table data with images converted to markdown syntax and long
            text truncated.
        """
        truncate_length = int(os.getenv("TRACKIO_TABLE_TRUNCATE_LENGTH", "250"))

        def convert_image_to_markdown(image_data: dict) -> str:
            relative_path = image_data.get("file_path", "")
            caption = image_data.get("caption", "")
            absolute_path = MEDIA_DIR / relative_path
            return f'<img src="/gradio_api/file={absolute_path}" alt="{caption}" />'

        processed_data = []
        for row in table_data:
            processed_row = {}
            for key, value in row.items():
                if isinstance(value, dict) and value.get("_type") == "trackio.image":
                    processed_row[key] = convert_image_to_markdown(value)
                elif (
                    isinstance(value, list)
                    and len(value) > 0
                    and isinstance(value[0], dict)
                    and value[0].get("_type") == "trackio.image"
                ):
                    # This assumes that if the first item is an image, all items are images. Ok for now since we don't support mixed types in a single cell.
                    processed_row[key] = (
                        '<div style="display: flex; gap: 10px;">'
                        + "".join([convert_image_to_markdown(item) for item in value])
                        + "</div>"
                    )
                elif isinstance(value, str) and len(value) > truncate_length:
                    truncated = value[:truncate_length]
                    full_text = value.replace("<", "&lt;").replace(">", "&gt;")
                    processed_row[key] = (
                        f'<details style="display: inline;">'
                        f'<summary style="display: inline; cursor: pointer;">{truncated}…<span><em>(truncated, click to expand)</em></span></summary>'
                        f'<div style="margin-top: 10px; padding: 10px; background: #f5f5f5; border-radius: 4px; max-height: 400px; overflow: auto;">'
                        f'<pre style="white-space: pre-wrap; word-wrap: break-word; margin: 0;">{full_text}</pre>'
                        f"</div>"
                        f"</details>"
                    )
                else:
                    processed_row[key] = value
            processed_data.append(processed_row)
        return processed_data

    def _to_dict(self, project: str, run: str, step: int = 0):
        """
        Converts the table to a dictionary representation.

        Args:
            project (`str`):
                Project name for saving media files.
            run (`str`):
                Run name for saving media files.
            step (`int`, *optional*, defaults to `0`):
                Step number for saving media files.
        """
        data = self._process_data(project, run, step)
        return {
            "_type": self.TYPE,
            "_value": data,
        }
