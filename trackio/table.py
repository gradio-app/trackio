from typing import Any, Literal

from pandas import DataFrame


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
        else:
            self.data = dataframe.to_dict(orient="records")

    def _to_dict(self):
        return {
            "_type": self.TYPE,
            "_value": self.data,
        }
