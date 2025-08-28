from typing import Any, List, Literal, Optional, Union

from pandas import DataFrame


class Table:
    TYPE = "trackio.table"

    def __init__(
        self,
        columns: Optional[List[str]] = None,
        data: Optional[List[List[Any]]] = None,
        dataframe: Optional[DataFrame] = None,
        rows: Optional[List[List[Any]]] = None,
        optional: Union[bool, List[bool]] = True,
        allow_mixed_types: bool = False,
        log_mode: Optional[
            Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"]
        ] = "IMMUTABLE",
    ):
        """
        Initializes a Table object.

        Args:
            columns: (List[str]) Names of the columns in the table.
                Optional if `data` is provided.
                Not expected if `dataframe` is provided.
                Currently ignored.
            data: (List[List[any]]) 2D row-oriented array of values.
            dataframe: (pandas.DataFrame) DataFrame object used to create the table.
                When set, `data` and `columns` arguments are ignored.
            rows: (List[List[any]]) Currently ignored.
            optional: (Union[bool,List[bool]]) Currently ignored.
            allow_mixed_types: (bool) Currently ignored.
            log_mode: (Optional[Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"]]) Currently ignored.
        """

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
