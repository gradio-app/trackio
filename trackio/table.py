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

    Args:
        columns (`list[str]`, *optional*):
            Names of the columns in the table. Optional if `data` is provided. Not
            expected if `dataframe` is provided. Currently ignored.
        data (`list[list[Any]]`, *optional*):
            2D row-oriented array of values.
        dataframe (`pandas.`DataFrame``, *optional*):
            DataFrame object used to create the table. When set, `data` and `columns`
            arguments are ignored.
        rows (`list[list[any]]`, *optional*):
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
        """Check if dataframe contains any TrackioMedia objects."""
        for col in dataframe.columns:
            if dataframe[col].apply(lambda x: isinstance(x, TrackioMedia)).any():
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

        return processed_df.to_dict(orient="records")

    @staticmethod
    def to_display_format(table_data: list[dict]) -> list[dict]:
        """Convert stored table data to display format for UI rendering.

        Args:
            table_data: List of dictionaries representing table rows (from stored _value)

        Returns:
            Table data with images converted to markdown syntax
        """
        # Fast path: check if any row contains trackio.image objects
        has_images = any(
            isinstance(value, dict) and value.get("_type") == "trackio.image"
            for row in table_data
            for value in row.values()
        )

        if not has_images:
            return table_data  # Return as-is if no images to process

        # Slow path: process images
        processed_data = []
        for row in table_data:
            processed_row = {}
            for key, value in row.items():
                if isinstance(value, dict) and value.get("_type") == "trackio.image":
                    relative_path = value.get("file_path", "")
                    caption = value.get("caption", "")
                    absolute_path = MEDIA_DIR / relative_path
                    processed_row[key] = (
                        f"![{caption}](/gradio_api/file={absolute_path})"
                    )
                else:
                    processed_row[key] = value
            processed_data.append(processed_row)

        return processed_data

    def _to_dict(self, project: str, run: str, step: int = 0):
        """Convert table to dictionary representation.

        Args:
            project: Project name for saving media files
            run: Run name for saving media files
            step: Step number for saving media files
        """
        data = self._process_data(project, run, step)
        return {
            "_type": self.TYPE,
            "_value": data,
        }
