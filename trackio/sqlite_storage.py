import os

_backend = (
    os.environ.get("TRACKIO_STORAGE_BACKEND")
    or os.environ.get("TRACKIO_STORAGE_ENGINE")
    or "parquet"
).strip().lower()

if _backend == "sqlite":
    from trackio.sqlite_backend import *  # noqa: F401,F403
elif _backend == "parquet":
    from trackio.parquet_storage import *  # noqa: F401,F403
else:
    raise ValueError(
        f"Unsupported Trackio storage backend '{_backend}'. Use 'parquet' or 'sqlite'."
    )
