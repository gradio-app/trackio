# Environment Variables

Trackio uses environment variables to configure various aspects of its behavior, particularly for deployment to Hugging Face Spaces and dataset persistence. This guide covers the main environment variables and their usage.

## Core Environment Variables

### `TRACKIO_DIR`

Specifies a custom directory for storing Trackio data. By default, Trackio stores data in `~/.cache/huggingface/trackio/`. 

```bash
export TRACKIO_DIR="/path/to/trackio/data"
```

Note: This environment variable applies as long as Trackio is not running in a Space with persistent storage enabled. If Trackio is running in a Space with persistent storage enabled (which is detected with the `PERSISTANT_STORAGE_ENABLED` env variable), then the Trackio data will be stored in `/data/trackio`.

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

### `TRACKIO_WEBHOOK_URL`

Sets a global webhook URL for alerts. When set, every call to `trackio.alert()` will POST the alert payload to this URL. Supports Slack and Discord webhook URLs natively (payloads are formatted automatically). Can be overridden per-alert or per-run via the `webhook_url` parameter.

```bash
export TRACKIO_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
```

See the [Alerts guide](alerts.md) for more details.

### `TRACKIO_DATASET_ID`

Sets the Hugging Face Dataset ID where logs will be stored when running on Hugging Face Spaces. If not provided, the dataset name will be set automatically when deploying to Spaces.


```bash
export TRACKIO_DATASET_ID="username/dataset_name"
```

### `HF_TOKEN`

Your Hugging Face authentication token. Required for creating Spaces and Datasets on Hugging Face. Set this locally when deploying to Spaces from your machine. Must have `write` permissions for the namespace that you are deploying the Trackio dashboard.

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


