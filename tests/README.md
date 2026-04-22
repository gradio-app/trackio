# Python Tests

This directory contains Python unit tests which can be run by running `pytest test` in the root directory.

This directory consists of 3 kinds of tests, all run with `pytest`:

1. Python tests in the `unit` subdirectory: most are classic unit tests for the corresponding module (e.g. `test_run.py` contains tests for `run.py`), and a few are lightweight local integration tests that still live under `unit`

2. UI tests run via Playright in the `ui` folder: each of the files in this folder contain UI tests that involve launching Trackio in the browser and confirming that the UI elements are present and interact as expected.

3. Finally directory also includes the `e2e-spaces` subdirectory, which deploy Trackio onto Spaces and then confirm that that the data is logged as expected.
