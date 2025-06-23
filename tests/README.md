This directory contains Python unit tests which can be run by running `pytest test` in the root directory.

Each of the `test_` files in this folder contain unit tests for the corresponding module (e.g. `test_run.py` contains unit tests for `run.py`)

This directory also includes the `e2e` subdirectory, which test the end-to-end user worfklow:

> User API (`__init__.py` or `run.py`) → Gradio UI (`ui.py`) → SQLite Storage (`sqlite_storage.py`)

