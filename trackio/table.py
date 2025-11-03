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
            self.data = data
            self._original_dataframe = None
        else:
            if self._has_media_objects(dataframe):
                # Store original dataframe for later media processing
                self._original_dataframe = dataframe.copy()
                # For now, store a placeholder that will be replaced during _to_dict
                self.data = None
            else:
                # No media objects, convert normally
                self.data = dataframe.to_dict(orient="records")
                self._original_dataframe = None

    def _has_media_objects(self, dataframe: DataFrame) -> bool:
        """Check if dataframe contains any TrackioMedia objects."""
        for col in dataframe.columns:
            if dataframe[col].apply(lambda x: isinstance(x, TrackioMedia)).any():
                return True
        return False

    def _serialize_media(self, df: DataFrame, project: str, run: str, step: int = 0):
        """Process TrackioMedia objects in dataframe by saving them and converting to dict representation."""
        processed_df = df.copy()

        for col in processed_df.columns:
            for idx in processed_df.index:
                value = processed_df.at[idx, col]
                if isinstance(value, TrackioMedia):
                    value._save(project, run, step)
                    processed_df.at[idx, col] = value._to_dict()

        return processed_df

    @staticmethod
    def to_display_format(table_data: list[dict]) -> tuple[list[dict], bool]:
        """Convert stored table data to display format for UI rendering.

        Args:
            table_data: List of dictionaries representing table rows (from stored _value)

        Returns:
            Tuple of (processed_data, has_images) where:
            - processed_data: Table data with images converted to markdown
            - has_images: Boolean indicating if any images were found
        """
        processed_data = []
        has_images = False

        for row in table_data:
            processed_row = {}
            for key, value in row.items():
                if isinstance(value, dict) and value.get("_type") == "trackio.image":
                    # Convert TrackioImage to markdown syntax with absolute path
                    relative_path = value.get("file_path", "")
                    caption = value.get("caption", "")
                    absolute_path = MEDIA_DIR / relative_path
                    # Use Gradio API format for markdown images in DataFrame
                    processed_row[key] = (
                        f"![{caption}](/gradio_api/file={absolute_path})"
                    )
                    has_images = True
                else:
                    processed_row[key] = value
            processed_data.append(processed_row)

        return processed_data, has_images

    def _to_dict(self, project: str = None, run: str = None, step: int = 0):
        """Convert table to dictionary representation.

        Args:
            project: Project name for saving media files
            run: Run name for saving media files
            step: Step number for saving media files
        """
        data = self.data

        # If we have a dataframe with media objects and the necessary context, process them
        if hasattr(self, "_original_dataframe") and project and run:
            processed_df = self._serialize_media(
                self._original_dataframe, project, run, step
            )
            data = processed_df.to_dict(orient="records")

        return {
            "_type": self.TYPE,
            "_value": data,
        }
