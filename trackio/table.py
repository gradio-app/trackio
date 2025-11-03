from typing import Any, Literal

from pandas import DataFrame

try:
    from trackio.media.media import TrackioMedia
except ImportError:
    from media.media import TrackioMedia


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
            # Check if dataframe contains any TrackioMedia objects
            has_media = False
            for col in dataframe.columns:
                if dataframe[col].apply(lambda x: isinstance(x, TrackioMedia)).any():
                    has_media = True
                    break

            if has_media:
                # Store original dataframe for later media processing
                self._original_dataframe = dataframe.copy()
                # For now, store a placeholder that will be replaced during _to_dict
                self.data = None
            else:
                # No media objects, convert normally
                self.data = dataframe.to_dict(orient="records")
                self._original_dataframe = None

    def _process_media_in_dataframe(
        self, df: DataFrame, project: str, run: str, step: int = 0
    ):
        """Process TrackioMedia objects in dataframe by saving them and converting to dict representation."""
        processed_df = df.copy()

        for col in processed_df.columns:
            for idx in processed_df.index:
                value = processed_df.at[idx, col]
                if isinstance(value, TrackioMedia):
                    value._save(project, run, step)
                    processed_df.at[idx, col] = value._to_dict()

        return processed_df

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
            processed_df = self._process_media_in_dataframe(
                self._original_dataframe, project, run, step
            )
            data = processed_df.to_dict(orient="records")

        return {
            "_type": self.TYPE,
            "_value": data,
        }
