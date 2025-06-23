# Python Unit Tests

This directory contains Python unit tests which can be run by running `pytest test` in the root directory.

Each of the `test_` files in this folder contain unit tests for the corresponding module (e.g. `test_run.py` contains unit tests for `run.py`)

This directory also includes the `e2e` subdirectory, which are also pytests, but test behaviors that include the end-to-end user worfklow:

> User API  → Gradio UI → SQLite Storage

(e.g. `test_import_from_csv.py` confirms that if a user runs `trackio.import_csv`, their data will successfully get sent to the Gradio app & then logged to the Sqlite DB)

