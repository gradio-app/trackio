from typing import Literal, Optional


class Table:
    def __init__(
        self,
        columns=None,
        data=None,
        rows=None,
        dataframe=None,
        dtype=None,
        optional=True,
        allow_mixed_types=False,
        log_mode: Optional[
            Literal["IMMUTABLE", "MUTABLE", "INCREMENTAL"]
        ] = "IMMUTABLE",
    ):
        # TODO: implement support for columns, dtype, optional, allow_mixed_types, and log_mode.
        # for now (like `rows`) they are included for API compat but don't do anything.

        if dataframe is None:
            self.data = data
        else:
            self.data = dataframe.to_dict(orient="records")

    def to_dict(self):
        return self.data
