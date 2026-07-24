# Environment Variables

Trackio uses environment variables to configure various aspects of its behavior, particularly for deployment to Hugging Face Spaces and data persistence. This guide covers the main environment variables and their usage.

## Core Environment Variables

### `TRACKIO_DIR`

Specifies a custom directory for storing Trackio data. By default, Trackio stores data in `~/.cache/huggingface/trackio/`. 

```bash
export TRACKIO_DIR="/path/to/trackio/data"
```

Note: This environment variable applies as long as Trackio is not running in a Space with persistent storage enabled. If Trackio is running in a Space with persistent storage enabled (which is detected with the `PERSISTANT_STORAGE_ENABLED` env variable), then the Trackio data will be stored in `/data/trackio`.

### `TRACKIO_SERVER_URL`

Base URL of a self-hosted Trackio server (`http://` or `https://`). You may include `write_token` in the query string (as in the `full_url` from `trackio.show()`), or keep the URL bare and set `TRACKIO_WRITE_TOKEN` instead. When set, `trackio.init()` sends metrics to that server. Equivalent to passing `server_url=` to `trackio.init()`.

**Precedence:** If `TRACKIO_SPACE_ID` is also set (or `space_id` is passed in code), the Hugging Face Space is used and `TRACKIO_SERVER_URL` is ignored. Same rule when both `space_id` and `server_url` are passed: `space_id` wins.

See [Self-host the Server](self_hosted_server.md).

```bash
export TRACKIO_SERVER_URL="http://127.0.0.1:7860"
export TRACKIO_WRITE_TOKEN="YOUR_TOKEN"
```

### `TRACKIO_WRITE_TOKEN`

The dashboard **write token** for a self-hosted Trackio server (same value as the `write_token` query parameter in the write-access URL). When set on the Trackio server, this value is used as the server's write token instead of generating a random token at startup. When set on the Trackio client, use this when `TRACKIO_SERVER_URL` or `server_url` is a base URL without query parameters. The client sends this token on each request (for example as the `X-Trackio-Write-Token` header) so metric ingestion and uploads are authenticated when not running on Hugging Face Spaces.

### `TRACKIO_FRONTEND_DIR`

Path to a custom static frontend directory for Trackio. The directory must contain `index.html`.

When set, Trackio uses that frontend for `trackio.show()` and for deploy flows such as `trackio.sync()` and `trackio.freeze()`, unless an explicit `frontend_dir` / `--frontend` argument is passed.

```bash
export TRACKIO_FRONTEND_DIR="/path/to/my-trackio-frontend"
```

If the configured directory is invalid, Trackio ignores it and falls back to the built-in frontend selection logic. The automatic starter-template copy behavior only applies when an explicit `frontend_dir` / `--frontend` argument points to a missing or empty directory.

### `TRACKIO_LOGO_LIGHT_URL` and `TRACKIO_LOGO_DARK_URL`

Customize the logos displayed in the Trackio dashboard for light and dark themes. You can provide URLs to custom logos. Note that both environment variables should be supplied; otherwise, the Trackio default will be used for any variable that is not provided.

```bash
export TRACKIO_LOGO_LIGHT_URL="https://example.com/logo-light.png"
export TRACKIO_LOGO_DARK_URL="https://example.com/logo-dark.png"
```

> **Note:** For remote Trackio Spaces, these environment variables are only applied when the Space is first created via `trackio.init(space_id=...)`. To change logos on an existing Space, update the Space variables directly in the Hugging Face Space settings.

### `TRACKIO_PLOT_ORDER`

Controls the ordering of plots and metric groups in the Trackio dashboard. The value should be a comma-separated list of metric patterns that specify the desired order. Groups are preserved - if `train/loss` is specified first, all other `train/*` metrics will appear together in the train group, with `train/loss` appearing first within that group.

If a pattern doesn't match any metrics, it's simply ignored without causing errors.

```bash
export TRACKIO_PLOT_ORDER="train/loss,val/loss"


**Pattern Matching:**
- **Exact matches**: `train/loss` matches exactly `train/loss`
- **Group wildcards**: `train/*` matches all metrics starting with `train/`
- **Partial wildcards**: `*gpu*` matches any metric containing "gpu"

**Behavior:**
- Metrics are grouped first (e.g., all `train/*` metrics stay together)
- Within each group, metrics are ordered according to the specified patterns
- Groups appear in the order of their first matching pattern
- Unspecified metrics appear in alphabetical order after specified ones

> **Note:** For remote Trackio Spaces, this environment variable is only applied when the Space is first created via `trackio.init(space_id=...)`. To change the plot order on an existing Space, update the `TRACKIO_PLOT_ORDER` Space variable directly in the Hugging Face Space settings.

### `TRACKIO_THEME`

Sets the theme for the Trackio dashboard. Can be a built-in Gradio theme name or a theme from the Hugging Face Hub.

```bash
# Built-in themes
export TRACKIO_THEME="soft"
export TRACKIO_THEME="citrus"
export TRACKIO_THEME="monochrome"

# Themes from the Hub
export TRACKIO_THEME="gstaff/xkcd"
export TRACKIO_THEME="ParityError/Anime"
```

> **Note:** For remote Trackio Spaces, this environment variable is only applied when the Space is first created via `trackio.init(space_id=...)`. To change the theme on an existing Space, update the `TRACKIO_THEME` Space variable directly in the Hugging Face Space settings.

### `TRACKIO_COLOR_PALETTE`

Customizes the color palette used for plot lines in the Trackio dashboard. The value should be a comma-separated list of hex color codes. These colors will be cycled through when plotting multiple runs.

```bash
export TRACKIO_COLOR_PALETTE="#FF0000,#00FF00,#0000FF,#FFFF00,#FF00FF,#00FFFF"
```

**Default palette:**
`#A8769B, #E89957, #3B82F6, #10B981, #EF4444, #8B5CF6, #14B8A6, #F59E0B, #EC4899, #06B6D4`

### `TRACKIO_TABLE_TRUNCATE_LENGTH`

Controls the maximum length of string values displayed in table cells before they are truncated. When a cell value exceeds this length, it will be truncated with an expandable element that allows viewing the full text. Defaults to `250` characters.

```bash
export TRACKIO_TABLE_TRUNCATE_LENGTH="500"
```

### `TRACKIO_STORAGE_MODE`

Controls how Trackio persists data locally. Allowed values: `auto` (default), `sqlite`, `jsonl`.

- `sqlite`: training processes write directly to the project SQLite database (the historical behavior).
- `jsonl`: training processes write append-only JSONL fragments to `TRACKIO_DIR/inbox/`, one file per process; the dashboard server (`trackio show`) imports them into SQLite. This avoids concurrent SQLite writers entirely, which makes Trackio safe on network filesystems (NFS, Lustre, FSx, GPFS, WekaFS, CephFS, ...) where SQLite's locking and mmap semantics are unreliable.
- `auto`: picks `jsonl` automatically when `TRACKIO_DIR` is detected to be on a network filesystem (Linux only), otherwise `sqlite`.

```bash
export TRACKIO_STORAGE_MODE="jsonl"
```

### `TRACKIO_INBOX_POLL_INTERVAL`

How often (in seconds) the dashboard server and Trackio Spaces check for new JSONL fragments to import, both from the local inbox directory and from the Hugging Face Bucket inbox. Defaults to `15`; values below `5` are clamped to `5`.

```bash
export TRACKIO_INBOX_POLL_INTERVAL="30"
```

### `TRACKIO_SQLITE_*` (advanced)

Override the PRAGMAs Trackio sets on its SQLite connections. These are mainly useful on unusual filesystems; invalid values are ignored.

- `TRACKIO_SQLITE_JOURNAL_MODE`: one of `wal`, `delete`, `truncate`, `persist`, `memory`, `off`. Defaults to `wal` locally and `delete` on Spaces.
- `TRACKIO_SQLITE_MMAP_SIZE`: memory-mapped I/O size in bytes. Defaults to `0` (disabled) everywhere, since memory-mapped reads are the direct trigger for SIGBUS crashes on network filesystems and win little for Trackio's workload.
- `TRACKIO_SQLITE_SYNCHRONOUS`: one of `off`, `normal`, `full`, `extra`. Defaults to `normal`.
- `TRACKIO_SQLITE_LOCKING_MODE`: one of `normal`, `exclusive`. Defaults to `exclusive` on Spaces, `normal` elsewhere.
- `TRACKIO_SQLITE_TEMP_STORE`: one of `default`, `file`, `memory`. Defaults to `memory`.

**Recommended cluster setup:** if your home or cache directory lives on a shared filesystem (`/fsx`, Lustre, NFS, GPFS, WekaFS, ...), either point `TRACKIO_DIR` at node-local disk (e.g. `/tmp` or `$SLURM_TMPDIR`), or rely on `TRACKIO_STORAGE_MODE=auto` which detects network filesystems and switches to JSONL fragment logging. If you must write SQLite directly on a shared filesystem, set:

```bash
export TRACKIO_SQLITE_JOURNAL_MODE="delete"
export TRACKIO_SQLITE_MMAP_SIZE="0"
```

### `TRACKIO_WEBHOOK_URL`

Sets a global webhook URL for alerts. When set, every call to `trackio.alert()` will POST the alert payload to this URL. Supports Slack and Discord webhook URLs natively (payloads are formatted automatically). Can be overridden per-alert or per-run via the `webhook_url` parameter.

```bash
export TRACKIO_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
```

See the [Alerts guide](alerts.md) for more details.

### `TRACKIO_WEBHOOK_MIN_LEVEL`

Sets the minimum alert level that should be sent to webhooks. Alerts below this level are still printed to terminal, stored in the database, and shown in the dashboard, but are not sent to webhook destinations.

Allowed values: `info`, `warn`, `error`.

```bash
export TRACKIO_WEBHOOK_MIN_LEVEL="warn"
```

With `warn`, only `WARN` and `ERROR` alerts are sent to webhook URLs.

### `TRACKIO_BUCKET_ID`

The ID of the Hugging Face Bucket (e.g. `username/bucketname`) used to persist Trackio data when running on a Hugging Face Space. This is normally set automatically on the Space when it is created via `trackio.init(space_id=...)` or `trackio.sync(...)`; a bucket is auto-generated from the Space ID unless an explicit `bucket_id` is provided.

```bash
export TRACKIO_BUCKET_ID="username/my-trackio-bucket"
```

### `TRACKIO_DATASET_ID` (deprecated)

> **Deprecated:** Persisting Trackio data to a Hugging Face Dataset (`dataset_id` / `TRACKIO_DATASET_ID`) is deprecated and will be removed in a future version of Trackio. Use a Hugging Face Bucket instead (`bucket_id` / `TRACKIO_BUCKET_ID`).

The ID of the Hugging Face Dataset (e.g. `username/datasetname`) that a Trackio Space syncs its data to via a background commit scheduler. When set on a Space, Trackio emits a deprecation warning and continues to sync to the Dataset for now.

```bash
export TRACKIO_DATASET_ID="username/my-trackio-dataset"
```

### `HF_TOKEN`

Your Hugging Face authentication token. Required for creating Spaces and Buckets on Hugging Face. Set this locally when deploying to Spaces from your machine. Must have `write` permissions for the namespace that you are deploying the Trackio dashboard.

```bash
export HF_TOKEN="hf_xxxxxxxxxxxxx"
```


## Gradio Environment Variables

Since Trackio is built on top of Gradio, you can use environment variables used by Gradio to control the behavior of Trackio. Here are a few examples:


### `GRADIO_SERVER_PORT`

Specifies the port on which the Tradio dashboard will launch. Defaults to `7860`

```bash
export GRADIO_SERVER_PORT=8000
```

### `GRADIO_SERVER_NAME`

Defines the host name for the Trackio dashboard server. To make the dasbhoard accessible from any IP address, set this to `"0.0.0.0"`

```bash
export GRADIO_SERVER_NAME="0.0.0.0"
```

### `GRADIO_MCP_SERVER`

Enables the MCP (Model Context Protocol) server functionality in Trackio. When enabled, the Trackio dashboard will be set up as an MCP server and certain functions will be exposed as MCP tools that can be used by LLMs (e.g. to read the logged metrics).

```bash
export GRADIO_MCP_SERVER="True"
```



See [this more comprehensive list](https://www.gradio.app/guides/environment-variables) of environment variables used by Gradio.
