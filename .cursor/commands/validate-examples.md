---
description: Stress-test the Trackio library via random examples, CLI, and Playwright UI
argument-hint: "[--count 3] [--seed 42] [--jobs 3] [--space username/space] [--continue-on-failure]"
---

Run the Trackio library validator (examples are only the workload; failures are interpreted as possible Trackio regressions):

`python scripts/validate_examples.py $ARGUMENTS`

If dependencies are missing, install dev dependencies first:

`pip install -e .[dev,tensorboard]`

Behavior:

- Runs a random subset of `examples/` scripts (default `--count 3`) to exercise logging, imports, and CLI
- Uses isolated `TRACKIO_DIR` per run (one shared DB when `--jobs 1`, separate sandboxes when `--jobs` > 1)
- **Sequential vs parallel:** default is **parallel** (`--jobs 3`). Use **`--jobs N`** to tune worker count; use `--jobs 1` for sequential mode. CLI checks and UI driving stay sequential afterward so ports and Playwright stay stable
- After successful example runs, validates **Trackio CLI** (`list` / `get` with JSON) and the **dashboard** via Playwright (tabs, checkboxes, screenshots)
- Collects **Trackio-related** signals (tracebacks touching `trackio`, CLI failures, dashboard console/page issues, etc.), **deduplicates** them, and prints a **`=== Trackio library health report ===`** section at the end. Exit code is non-zero if anything was collected or an example run failed (unless you stop early without `--continue-on-failure`)
- Writes `summary.json` under the artifacts directory (includes `trackio_issues` and paths)
- For remote Spaces data, pass **`--space`** to CLI-backed checks as documented in the Trackio CLI

Optional:

- `--continue-on-failure` — run the remaining examples after a failure; CLI/UI run only for examples that completed successfully
