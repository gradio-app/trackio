# CLI Commands

Trackio provides a comprehensive set of CLI commands that enable you to query project, run, and metric information without needing to start the MCP server. Commands work against local data by default, or against a remote HF Space when `--space` is provided. This is particularly useful for LLM agents and automation scripts. With structured JSON output and programmatic access to all experiment data, Trackio is designed to support autonomous ML experiments run by LLMs.

## Querying Remote Spaces

All `list` and `get` commands support querying a remote Hugging Face Space instead of local data. Pass the `--space` flag with either a Space ID or full URL:

```sh
# Using a Space ID
trackio list projects --space username/my-space

# Using a Space URL
trackio list projects --space https://username-my-space.hf.space

# Works with any list/get command
trackio get metric --project "my-project" --run "my-run" --metric "loss" --space username/my-space
```

For private Spaces, pass `--hf-token` or ensure you are logged in via `huggingface-cli login`:

```sh
trackio list projects --space username/private-space --hf-token hf_xxxxx
```

> **Note:** The `show`, `status`, `sync`, `freeze`, and `skills` commands are local-only and do not support `--space`.

## Sync Command

Upload a local project to a Hugging Face Space:

```sh
trackio sync --project "my-project" --space-id "username/space_id"
```

Deploy as a static Space (reads from an HF Bucket, no server needed):

```sh
trackio sync --project "my-project" --space-id "username/space_id" --sdk static
```

Sync all projects that have unsynced data to their configured Spaces:

```sh
trackio sync --all
```

| Flag | Description |
|------|-------------|
| `--project` | The name of the project to sync (required unless `--all` is used) |
| `--space-id` | The HF Space ID to sync to (e.g. `username/space_id`). If not provided, uses the previously-configured Space |
| `--all` | Sync all projects with unsynced data |
| `--sdk` | `gradio` (default) for a live server, or `static` for a read-only bucket-backed Space |
| `--private` | Make the Space private if creating a new one |
| `--force` | Overwrite the existing database without prompting |

## Freeze Command

Create a read-only static Space snapshot from a live Gradio Space:

```sh
trackio freeze --space-id "username/my-space" --project "my-project"
```

Specify a custom destination Space:

```sh
trackio freeze --space-id "username/my-space" --project "my-project" --new-space-id "username/my-snapshot"
```

| Flag | Description |
|------|-------------|
| `--space-id` | The source Gradio Space ID (required) |
| `--project` | The project to freeze (required) |
| `--new-space-id` | The destination static Space ID. Defaults to `{space_id}_static` |
| `--private` | Make the new static Space private |

> **Note:** The source must be a Gradio Space with a bucket mounted at `/data`. If the destination Space already exists and is not a Trackio static Space, `freeze` will refuse to overwrite it.
> The frozen Space is a snapshot. Later metrics synced to the original Gradio Space do not appear in the frozen static Space unless you run `freeze` again.

## List Commands

### List All Projects

List all available projects:

```sh
trackio list projects
```

Output in JSON format:

```sh
trackio list projects --json
```

### List Runs for a Project

List all runs in a specific project:

```sh
trackio list runs --project "my-project"
```

Output in JSON format:

```sh
trackio list runs --project "my-project" --json
```

### List Metrics for a Run

List all metrics tracked in a specific run:

```sh
trackio list metrics --project "my-project" --run "my-run"
```

Output in JSON format:

```sh
trackio list metrics --project "my-project" --run "my-run" --json
```

### List System Metrics for a Run

List all system metrics (e.g., GPU metrics) for a specific run:

```sh
trackio list system-metrics --project "my-project" --run "my-run"
```

Output in JSON format:

```sh
trackio list system-metrics --project "my-project" --run "my-run" --json
```

### List Reports

List markdown reports in a project (across all runs):

```sh
trackio list reports --project "my-project"
```

List markdown reports for a specific run:

```sh
trackio list reports --project "my-project" --run "my-run"
```

Output in JSON format:

```sh
trackio list reports --project "my-project" --run "my-run" --json
```

## Get Commands

### Get Project Summary

Get a detailed summary of a project, including the number of runs and recent activity:

```sh
trackio get project --project "my-project"
```

Output in JSON format:

```sh
trackio get project --project "my-project" --json
```

The summary includes:
- Project name
- Number of runs
- List of all runs
- Last activity (maximum step across all runs)

### Get Run Summary

Get a detailed summary of a specific run, including metrics and configuration:

```sh
trackio get run --project "my-project" --run "my-run"
```

Output in JSON format:

```sh
trackio get run --project "my-project" --run "my-run" --json
```

The summary includes:
- Project and run names
- Number of log entries
- Last step
- List of all metrics
- Run configuration (excluding internal fields)

### Get Metric Values

Get all values for a specific metric in a run:

```sh
trackio get metric --project "my-project" --run "my-run" --metric "loss"
```

Output in JSON format:

```sh
trackio get metric --project "my-project" --run "my-run" --metric "loss" --json
```

The output includes:
- Step number
- Timestamp
- Metric value

#### Filtering by Step or Time

You can filter metric values to a specific step or a window around a step/timestamp. This is useful for inspecting metrics around the time an alert was fired.

```sh
# Get metric at exactly step 200
trackio get metric --project "my-project" --run "my-run" --metric "loss" --step 200

# Get metrics in a window around step 200 (±10 steps, the default)
trackio get metric --project "my-project" --run "my-run" --metric "loss" --around 200

# Get metrics in a window around step 200 (±50 steps)
trackio get metric --project "my-project" --run "my-run" --metric "loss" --around 200 --window 50

# Get metrics within ±60 seconds of a timestamp
trackio get metric --project "my-project" --run "my-run" --metric "loss" --at-time "2025-06-01T12:05:30" --window 60
```

| Flag | Description |
|------|-------------|
| `--step N` | Return the metric at exactly step N |
| `--around N` | Return metrics in a window around step N |
| `--at-time T` | Return metrics in a window around ISO 8601 timestamp T |
| `--window W` | Window size: ±steps for `--around`, ±seconds for `--at-time` (default: 10) |

### Get Metrics Snapshot

Get **all** metrics at/around a step or timestamp in a single call. This is the fastest way for an agent to understand the state of a run at a specific point — for example, right when an alert fired.

```sh
# All metrics at step 200
trackio get snapshot --project "my-project" --run "my-run" --step 200 --json

# All metrics in a window around step 200 (±5 steps)
trackio get snapshot --project "my-project" --run "my-run" --around 200 --window 5 --json

# All metrics within ±60 seconds of a timestamp
trackio get snapshot --project "my-project" --run "my-run" --at-time "2025-06-01T12:05:30" --window 60 --json
```

Example JSON output:

```json
{
  "project": "my-project",
  "run": "my-run",
  "around": 200,
  "window": 5,
  "metrics": {
    "loss": [
      {"step": 196, "timestamp": "2025-06-01T12:04:50", "value": 0.42},
      {"step": 200, "timestamp": "2025-06-01T12:05:30", "value": 0.45}
    ],
    "accuracy": [
      {"step": 196, "timestamp": "2025-06-01T12:04:50", "value": 0.88},
      {"step": 200, "timestamp": "2025-06-01T12:05:30", "value": 0.87}
    ],
    "lr": [
      {"step": 196, "timestamp": "2025-06-01T12:04:50", "value": 0.0001},
      {"step": 200, "timestamp": "2025-06-01T12:05:30", "value": 0.0001}
    ]
  }
}
```

### Get System Metric Values

Get system metric values for a run. If no metric name is provided, all system metrics are returned:

```sh
# Get all system metrics
trackio get system-metric --project "my-project" --run "my-run"

# Get a specific system metric
trackio get system-metric --project "my-project" --run "my-run" --metric "gpu_utilization"
```

Output in JSON format:

```sh
trackio get system-metric --project "my-project" --run "my-run" --metric "gpu_utilization" --json
```

### Get Report Content

Print markdown report entries for a specific report name in a run:

```sh
trackio get report --project "my-project" --run "my-run" --report "training_report"
```

Output in JSON format:

```sh
trackio get report --project "my-project" --run "my-run" --report "training_report" --json
```

## Output Formats

All commands support two output formats:

1. **Human-readable** (default): Formatted text output suitable for terminal viewing
2. **JSON** (with `--json` flag): Structured JSON output suitable for programmatic consumption

## Error Handling

The CLI commands include comprehensive validation and error handling:

- If a project doesn't exist, an error message is displayed
- If a run doesn't exist in a project, an error message is displayed
- If a metric doesn't exist in a run, an error message is displayed
- If a report doesn't exist in a run, an error message is displayed

All errors are written to stderr and the command exits with a non-zero exit code.

## Example Workflow

Here's a typical workflow for exploring your Trackio data:

```sh
# 1. List all projects
trackio list projects

# 2. List runs in a project
trackio list runs --project "my-project"

# 3. Get project summary
trackio get project --project "my-project"

# 4. Get run summary
trackio get run --project "my-project" --run "my-run"

# 5. List metrics in the run
trackio list metrics --project "my-project" --run "my-run"

# 6. Get specific metric values
trackio get metric --project "my-project" --run "my-run" --metric "loss"

# 7. Get all metrics at a specific step (e.g. where an alert fired)
trackio get snapshot --project "my-project" --run "my-run" --step 200 --json

# 8. Get system metrics (if available)
trackio list system-metrics --project "my-project" --run "my-run"

# 9. List reports in a run
trackio list reports --project "my-project" --run "my-run"

# 10. Print report markdown in terminal
trackio get report --project "my-project" --run "my-run" --report "training_report"
```

### Querying a Remote Space

The same workflow works against a remote Space — just add `--space`:

```sh
# List projects on a remote Space
trackio list projects --space username/my-space

# Get metric values from a remote Space
trackio get metric --project "my-project" --run "my-run" --metric "loss" --space username/my-space --json
```

## Use Cases

### LLM Agents

These CLI commands are particularly useful for LLM agents that need to:
- Discover available projects and runs
- Query metric values programmatically
- Inspect metrics around an alert with `get snapshot` or `get metric --around`
- Get summaries without starting a server
- Parse structured JSON output for further processing

### Automation Scripts

You can use these commands in shell scripts and automation pipelines:

```sh
#!/bin/bash
PROJECT="my-project"
RUN="my-run"

# Get the latest loss value
LATEST_LOSS=$(trackio get metric --project "$PROJECT" --run "$RUN" --metric "loss" --json | jq -r '.values[-1].value')
echo "Latest loss: $LATEST_LOSS"
```

### Integration with Other Tools

The JSON output format makes it easy to integrate with other tools:

```sh
# Pipe to jq for filtering
trackio list runs --project "my-project" --json | jq '.runs[] | select(startswith("train"))'

# Export to file
trackio get run --project "my-project" --run "my-run" --json > run_summary.json
```
