# CLI Commands

Trackio provides a comprehensive set of CLI commands that enable you to query project, run, and metric information locally without needing to start the MCP server. This is particularly useful for LLM agents and automation scripts. With structured JSON output and programmatic access to all experiment data, Trackio is designed to support autonomous ML experiments run by LLMs.

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

## Output Formats

All commands support two output formats:

1. **Human-readable** (default): Formatted text output suitable for terminal viewing
2. **JSON** (with `--json` flag): Structured JSON output suitable for programmatic consumption

## Error Handling

The CLI commands include comprehensive validation and error handling:

- If a project doesn't exist, an error message is displayed
- If a run doesn't exist in a project, an error message is displayed
- If a metric doesn't exist in a run, an error message is displayed

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

# 7. Get system metrics (if available)
trackio list system-metrics --project "my-project" --run "my-run"
```

## Use Cases

### LLM Agents

These CLI commands are particularly useful for LLM agents that need to:
- Discover available projects and runs
- Query metric values programmatically
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

