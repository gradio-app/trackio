# Python Tests

This directory contains Python unit tests which can be run by running `pytest test` in the root directory.

This directory consists of 4 kinds of tests, all run with `pytest`:

1. Python unit tests in the `unit` subdirectory: each of the `test_` files in this folder contain unit tests for the corresponding module (e.g. `test_run.py` contains unit tests for `run.py`)

2. UI tests run via Playright in the `ui` folder: each of the files in this folder contain UI tests that involve launching Trackio in the browser and confirming that the UI elements are present and interact as expected.

3. End-to-end local tests in the `e2e-local` subdirectory: which are also local tests, but test behaviors that include the end-to-end user workflow: `User API  → Gradio UI → SQLite Storage`

4. Finally directory also includes the `e2e-spaces` subdirectory, which deploy Trackio onto Spaces and then confirm that that the data is logged as expected. 

