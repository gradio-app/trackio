# Retrieving Metrics with Trackio CLI

The `trackio` CLI provides direct terminal access to query Trackio experiment tracking data without needing to start the MCP server. Commands work against local data by default, or against a remote HF Space when `--space` is provided.

## Quick Command Reference

| Task | Command |
|------|---------|
| List projects | `trackio list projects` |
| List runs | `trackio list runs --project <name>` |
| List metrics | `trackio list metrics --project <name> --run <name>` |
| List system metrics | `trackio list system-metrics --project <name> --run <name>` |
| List alerts | `trackio list alerts --project <name> [--run <name>] [--level <level>] [--since <timestamp>]` |
| List traces | `trackio list traces --project <name> [--run <name>] [--search <text>] [--step <N>]` |
| Get project summary | `trackio get project --project <name>` |
| Get run summary | `trackio get run --project <name> --run <name>` |
| Get metric values | `trackio get metric --project <name> --run <name> --metric <name>` |
| Get metric at step | `trackio get metric ... --metric <name> --step <N>` |
| Get metric around step | `trackio get metric ... --metric <name> --around <N> --window <W>` |
| Get all metrics snapshot | `trackio get snapshot --project <name> --run <name> --step <N>` |
| Get system metrics | `trackio get system-metric --project <name> --run <name>` |
| Get one trace + span tree | `trackio get trace --project <name> --trace-id <id>` |
| Roll up trace operations | `trackio get trace-summary --project <name> [--run <name>]` |
| Run direct SQL | `trackio query project --project <name> --sql "SELECT ..."` |
| Query remote Space | `trackio list projects --space <space_id_or_url>` |
| Show dashboard | `trackio show [--project <name>]` |
| Sync to Space | `trackio sync --project <name> --space-id <space_id>` |

## Core Commands

### List Commands

```bash
trackio list projects                                    # List all projects
trackio list projects --json                            # JSON output

trackio list runs --project <name>                      # List runs in project
trackio list runs --project <name> --json               # JSON output

trackio list metrics --project <name> --run <name>      # List metrics for run
trackio list metrics --project <name> --run <name> --json

trackio list system-metrics --project <name> --run <name>  # List system metrics
trackio list system-metrics --project <name> --run <name> --json

trackio list alerts --project <name>                       # List alerts
trackio list alerts --project <name> --run <name> --json   # Filter by run
trackio list alerts --project <name> --level error --json  # Filter by level
trackio list alerts --project <name> --json --since <ts>   # Poll since timestamp
```

### Get Commands

```bash
trackio get project --project <name>                    # Project summary
trackio get project --project <name> --json             # JSON output

trackio get run --project <name> --run <name>           # Run summary
trackio get run --project <name> --run <name> --json

trackio get metric --project <name> --run <name> --metric <name>  # Metric values
trackio get metric --project <name> --run <name> --metric <name> --json
trackio get metric ... --metric <name> --step 200                 # At exact step
trackio get metric ... --metric <name> --around 200 --window 10   # ±10 steps
trackio get metric ... --metric <name> --at-time <ts> --window 60 # ±60 seconds

trackio get snapshot --project <name> --run <name> --step 200 --json       # All metrics at step
trackio get snapshot --project <name> --run <name> --around 200 --window 5 --json  # Window
trackio get snapshot --project <name> --run <name> --at-time <ts> --window 60 --json

trackio get system-metric --project <name> --run <name>           # All system metrics
trackio get system-metric --project <name> --run <name> --metric <name>  # Specific metric
trackio get system-metric --project <name> --run <name> --json
```

### Trace Commands

Traces are agent/LLM sessions: OpenAI-style messages plus execution spans
(model generations, tool calls) carrying latency, status, token usage, and cost.
Use these to answer questions about *production agent behaviour* — where latency
and spend go, which tools fail, how context grows.

```bash
trackio list traces --project <name>                          # Newest traces across all runs
trackio list traces --project <name> --run <name>             # One run
trackio list traces --project <name> --search "rate limit"    # Match messages, metadata, span names/models/errors
trackio list traces --project <name> --step 12                # Traces logged at one step
trackio list traces --project <name> --sort step_desc --limit 100
trackio list traces --project <name> --json                   # Adds a per-trace `summary` rollup

trackio get trace --project <name> --trace-id <id>            # Full span tree, per-span cost/tokens/errors
trackio get trace --project <name> --trace-id <id> --json

trackio get trace-summary --project <name>                    # Per-operation rollup across traces
trackio get trace-summary --project <name> --run <name> --json
```

`list traces` prints the short trace id (the `log_id` segment); `get trace`
accepts either that or the full stored id.

`get trace-summary` groups every span by operation name and returns calls,
errors, avg/max latency in ms, input/output tokens, and cost — the fastest way
to find what to improve:

```bash
$ trackio get trace-summary --project paperswithcode-chat
operation                  | kind       | calls | errors | avg_ms  | max_ms  | input_tokens | output_tokens | cost_usd
provider-request           | generation | 205   | 0      | 3380.8  | 5535.0  | 2915829      | 63020         | 9.6928
run-bash-command           | tool       | 157   | 25     | 818.4   | 1548.0  | 0            | 0             | 0.0
acquire-sandbox            | span       | 48    | 0      | 2438.6  | 10615.0 | 0            | 0             | 0.0
```

Read that as: input tokens are 98% of all tokens (context is being re-sent, so
prompt caching is the biggest cost lever), 25 of 157 tool calls fail, and
`acquire-sandbox` has a 10.6s worst case against a 2.4s average (cold starts).

For anything the rollup does not cover, query the `traces` table directly. The
`spans` column is JSON, so `json_each` works:

```bash
# Which tool failures happen, and in how many sessions?
trackio query project --project <name> --sql "
SELECT json_extract(s.value,'\$.name') AS op,
       json_extract(s.value,'\$.error.stderr') AS stderr,
       COUNT(*) AS failures, COUNT(DISTINCT traces.id) AS sessions
FROM traces, json_each(traces.spans) AS s
WHERE json_extract(s.value,'\$.status') = 'error'
GROUP BY op, stderr ORDER BY failures DESC"
```

### Query Command

```bash
trackio query project --project <name> --sql "SELECT name FROM sqlite_master WHERE type = 'table'"
trackio query project --project <name> --sql "PRAGMA table_info(metrics)" --json
trackio query project --project <name> --sql "SELECT run_name, MAX(step) AS last_step FROM metrics GROUP BY run_name"
```

### Remote Space Queries

All `list`, `get`, and `query` commands support querying a remote HF Space with `--space`:

```bash
trackio list projects --space user/my-space              # Space ID
trackio list projects --space https://user-my-space.hf.space  # Space URL
trackio get metric --project <name> --run <name> --metric loss --space user/my-space
trackio query project --project <name> --sql "SELECT COUNT(*) AS num_alerts FROM alerts" --space user/my-space
trackio list projects --space user/private-space --hf-token hf_xxx  # Private Space
```

### Dashboard Commands

```bash
trackio show                                              # Launch dashboard
trackio show --project <name>                           # Load specific project
trackio show --theme <theme>                            # Custom theme
trackio show --mcp-server                                # Enable MCP server
trackio show --color-palette "#FF0000,#00FF00"         # Custom colors
```

### Sync Commands

```bash
trackio sync --project <name> --space-id <space_id>     # Sync to HF Space
trackio sync --project <name> --space-id <space_id> --private  # Private space
trackio sync --project <name> --space-id <space_id> --force   # Overwrite
```

## Output Formats

All `list`, `get`, and `query` commands support two output formats:

- **Human-readable** (default): Formatted text for terminal viewing
- **JSON** (with `--json` flag): Structured JSON for programmatic use

## Common Patterns

### Discover Projects and Runs

```bash
# List all available projects
trackio list projects

# List runs in a project
trackio list runs --project my-project

# Get project overview
trackio get project --project my-project --json
```

### Inspect Run Details

```bash
# Get run summary with all metrics
trackio get run --project my-project --run my-run --json

# List available metrics
trackio list metrics --project my-project --run my-run

# Get specific metric values
trackio get metric --project my-project --run my-run --metric loss --json
```

### Query System Metrics

```bash
# List system metrics (GPU, etc.)
trackio list system-metrics --project my-project --run my-run

# Get all system metric data
trackio get system-metric --project my-project --run my-run --json

# Get specific system metric
trackio get system-metric --project my-project --run my-run --metric gpu_utilization --json
```

### Automation Scripts

```bash
# Extract latest metric value
LATEST_LOSS=$(trackio get metric --project my-project --run my-run --metric loss --json | jq -r '.values[-1].value')

# Export run summary to file
trackio get run --project my-project --run my-run --json > run_summary.json

# Filter runs with jq
trackio list runs --project my-project --json | jq '.runs[] | select(startswith("train"))'

# Run a direct SQL aggregate
trackio query project --project my-project --sql "SELECT run_name, MAX(step) AS last_step FROM metrics GROUP BY run_name" --json
```

### LLM Agent Workflow

```bash
# 1. Discover available projects
trackio list projects --json

# 2. Explore project structure
trackio get project --project my-project --json

# 3. Inspect specific run
trackio get run --project my-project --run my-run --json

# 4. Query metric values
trackio get metric --project my-project --run my-run --metric accuracy --json

# 5. Poll for alerts (use --since for efficient incremental polling)
trackio list alerts --project my-project --json --since "2025-06-01T00:00:00"

# 6. When an alert fires at step N, get all metrics around that point
trackio get snapshot --project my-project --run my-run --around 200 --window 5 --json

# 7. Review production agent behaviour: rollup first, then drill into a trace
trackio get trace-summary --project <name> --json
trackio list traces --project <name> --search "error" --json
trackio get trace --project <name> --trace-id <id> --json

# 8. Fall back to direct SQL for one-off inspection
trackio query project --project my-project --sql "SELECT timestamp, run_name, level, title FROM alerts ORDER BY timestamp DESC LIMIT 20" --json
```

## Error Handling

Commands validate inputs and return clear errors:

- Missing project: `Error: Project '<name>' not found.`
- Missing run: `Error: Run '<name>' not found in project '<project>'.`
- Missing metric: `Error: Metric '<name>' not found in run '<run>' of project '<project>'.`

All errors exit with non-zero status code and write to stderr.

## Key Options

- `--project`: Project name (required for most commands)
- `--run`: Run name (required for run-specific commands)
- `--metric`: Metric name (required for metric-specific commands)
- `--sql`: Read-only SQL query (for `trackio query`)
- `--json`: Output in JSON format instead of human-readable
- `--space`: HF Space ID (e.g. `user/space`) or Space URL to query remotely (for `list`/`get`/`query` commands)
- `--hf-token`: HF token for accessing private Spaces (for `list`/`get`/`query` commands with `--space`)
- `--step`: Exact step filter (for `get metric`, `get snapshot`)
- `--around`: Center step for window filter (for `get metric`, `get snapshot`)
- `--at-time`: Center ISO timestamp for window filter (for `get metric`, `get snapshot`)
- `--window`: Window size: ±steps for `--around`, ±seconds for `--at-time` (default: 10)
- `--level`: Alert level filter (`info`, `warn`, `error`) (for `list alerts`)
- `--since`: ISO timestamp to filter alerts after (for `list alerts`)
- `--theme`: Dashboard theme (for `show` command)
- `--mcp-server`: Enable MCP server mode (for `show` command)
- `--color-palette`: Comma-separated hex colors (for `show` command)
- `--private`: Create private Space (for `sync` command)
- `--force`: Overwrite existing database (for `sync` command)

## JSON Output Structure

### List Projects
```json
{"projects": ["project1", "project2"]}
```

### List Runs
```json
{"project": "my-project", "runs": ["run1", "run2"]}
```

### Project Summary
```json
{
  "project": "my-project",
  "num_runs": 3,
  "runs": ["run1", "run2", "run3"],
  "last_activity": 100
}
```

### Run Summary
```json
{
  "project": "my-project",
  "run": "my-run",
  "num_logs": 50,
  "metrics": ["loss", "accuracy"],
  "config": {"learning_rate": 0.001},
  "last_step": 49
}
```

### Metric Values
```json
{
  "project": "my-project",
  "run": "my-run",
  "metric": "loss",
  "values": [
    {"step": 0, "timestamp": "2024-01-01T00:00:00", "value": 0.5},
    {"step": 1, "timestamp": "2024-01-01T00:01:00", "value": 0.4}
  ]
}
```

### Query Result
```json
{
  "project": "my-project",
  "query": "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
  "columns": ["name"],
  "rows": [
    {"name": "alerts"},
    {"name": "configs"},
    {"name": "metrics"}
  ],
  "row_count": 3
}
```

## References

- **Complete CLI documentation**: See [docs/source/cli_commands.md](docs/source/cli_commands.md)
- **Storage schema and direct SQL**: See [storage_schema.md](storage_schema.md)
- **API and MCP Server**: See [docs/source/api_mcp_server.md](docs/source/api_mcp_server.md)

