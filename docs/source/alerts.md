# Alerts

Trackio alerts let you flag important events during a run. When an alert fires, it is:

1. **Printed to the terminal** with a color-coded severity label
2. **Stored in the database** so it can be queried later via the CLI, Python API, or HTTP endpoint
3. **Displayed in the dashboard** on the Alerts page
4. **Sent to a webhook** (optional) — with native formatting for Slack and Discord

## Firing an Alert

Use [`alert`] anywhere after calling [`init`]:

```python
import trackio

trackio.init(project="my-project")

# ... inside your training loop ...
if val_loss > 2.0:
    trackio.alert(
        title="Validation loss spike",
        text=f"val_loss={val_loss:.4f} exceeded threshold 2.0",
        level=trackio.AlertLevel.ERROR,
    )
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `title` | `str` | *(required)* | A short title for the alert. |
| `text` | `str \| None` | `None` | An optional longer description with details. |
| `level` | `AlertLevel` | `AlertLevel.WARN` | Severity: `INFO`, `WARN`, or `ERROR`. |
| `webhook_url` | `str \| None` | `None` | Override the global webhook URL for this alert only. |

### Alert Levels

```python
from trackio import AlertLevel

AlertLevel.INFO   # Informational — nothing is wrong
AlertLevel.WARN   # Warning — something may need attention
AlertLevel.ERROR  # Error — something is definitely wrong
```

## Terminal Output

Every alert is printed to the terminal immediately, with a color-coded label:

```
[TRACKIO WARN] Validation loss spike: val_loss=2.3412 exceeded threshold 2.0 (step 42)
```

- **INFO** is printed in blue
- **WARN** is printed in yellow
- **ERROR** is printed in red

This means alerts work out of the box with no setup — if you can see your training logs, you can see your alerts.

## Dashboard

Alerts appear on the **Alerts** page in the Trackio dashboard. You can filter alerts by run name and severity level. The page auto-refreshes so new alerts appear without needing to reload.

To launch the dashboard:

```bash
trackio show --project "my-project"
```

Then click **Alerts** in the navigation bar.

## Querying Alerts

### CLI

```bash
# List all alerts for a project
trackio get alerts --project "my-project"

# Filter by run
trackio get alerts --project "my-project" --run "brave-sunset-0"

# Filter by level
trackio get alerts --project "my-project" --level error

# Only alerts after a specific timestamp (useful for polling)
trackio get alerts --project "my-project" --since "2025-06-01T00:00:00"

# JSON output for programmatic consumption
trackio get alerts --project "my-project" --json
```

### Python API

```python
import trackio

api = trackio.Api()

# All alerts in a project
alerts = api.alerts("my-project")

# Filter by run and level
alerts = api.alerts("my-project", run="brave-sunset-0", level="error")

# Only new alerts since a timestamp
alerts = api.alerts("my-project", since="2025-06-01T12:00:00")

# From a Run object
runs = api.runs("my-project")
run_alerts = runs[0].alerts(level="warn")
```

### HTTP API

If the Trackio dashboard is running (locally or on a Space), you can query alerts via the `/get_alerts` endpoint:

```python
from gradio_client import Client

client = Client("http://127.0.0.1:7860/")
alerts = client.predict(
    project="my-project",
    run=None,
    level="error",
    since="2025-06-01T00:00:00",
    api_name="/get_alerts",
)
```

## Webhooks

Webhooks let you push alerts to external services like Slack, Discord, or any HTTP endpoint.

### Setting a Global Webhook

You can set a webhook URL that applies to every alert in a run:

**Option 1: In `trackio.init()`**

```python
trackio.init(
    project="my-project",
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
)
```

**Option 2: Environment variable**

```bash
export TRACKIO_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
```

```python
# No webhook_url needed — picks up the env var automatically
trackio.init(project="my-project")
```

The env variable is convenient when you want the same webhook for all projects without changing code.

### Sending Only Higher-Severity Alerts to Webhooks

If you only want webhooks for important alerts, set `webhook_min_level` in `trackio.init()`:

```python
trackio.init(
    project="my-project",
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
    webhook_min_level=trackio.AlertLevel.WARN,
)
```

With `webhook_min_level=AlertLevel.WARN`:
- `INFO` alerts are still printed/stored/shown in UI, but not sent to webhook
- `WARN` and `ERROR` alerts are sent to webhook

You can also configure this globally with an environment variable:

```bash
export TRACKIO_WEBHOOK_MIN_LEVEL="warn"
```

### Overriding Per-Alert

Pass `webhook_url` directly to `trackio.alert()` to override the global setting for a single alert, or to send a specific alert to a different channel:

```python
trackio.alert(
    title="Checkpoint saved",
    text="Saved model at step 5000",
    level=trackio.AlertLevel.INFO,
    webhook_url="https://discord.com/api/webhooks/123456/abcdef",
)
```

### Webhook Payloads

Trackio auto-detects the service from the URL and formats the payload accordingly.

**Generic webhooks** receive a JSON POST body:

```json
{
    "level": "warn",
    "title": "Validation loss spike",
    "text": "val_loss=2.34 exceeded threshold 2.0",
    "project": "my-project",
    "run": "brave-sunset-0",
    "step": 42,
    "timestamp": "2025-06-15T14:30:00+00:00"
}
```

**Slack** and **Discord** receive rich formatted messages (see sections below).

Webhooks are sent in a background thread so `trackio.alert()` never blocks your training loop.

---

## Slack

### Creating a Slack Webhook

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** → **From scratch**.
2. Give the app a name (e.g., "Trackio Alerts") and select your workspace.
3. In the left sidebar, click **Incoming Webhooks** and toggle it **On**.
4. Click **Add New Webhook to Workspace**, select the channel you want alerts in, and click **Allow**.
5. Copy the webhook URL. It looks like:
   ```
   https://hooks.slack.com/services/TXXXXX/BXXXXX/XXXXXXXXXX
   ```

### Using it with Trackio

```python
trackio.init(
    project="my-project",
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
)

trackio.alert(
    title="Training complete",
    text="Final val_accuracy: 0.94",
    level=trackio.AlertLevel.INFO,
)
```

### What it looks like


Trackio sends Slack [Block Kit](https://api.slack.com/block-kit) messages with:
- A bold header with an emoji and severity level (e.g., "⚠️ **[WARN] Loss spike**")
- An optional description section with your `text`
- A context footer showing the project name, run name, and step number

<img height="108" alt="image" src="https://github.com/user-attachments/assets/9004eb22-68e4-4c06-9ed4-2319d8e56e9f" />

---

## Discord

### Creating a Discord Webhook

1. Open **Server Settings** → **Integrations** → **Webhooks**.
2. Click **New Webhook**.
3. Give it a name (e.g., "Trackio Alerts"), select the channel, and click **Copy Webhook URL**.
4. The URL looks like:
   ```
   https://discord.com/api/webhooks/123456789/ABCDEFghijklmnop
   ```

### Using it with Trackio

```python
trackio.init(
    project="my-project",
    webhook_url="https://discord.com/api/webhooks/123456789/ABCDEFghijklmnop",
)

trackio.alert(
    title="GPU temperature critical",
    text="GPU 0 reached 95°C",
    level=trackio.AlertLevel.ERROR,
)
```

### What it looks like

Trackio sends Discord [Embed](https://discord.com/developers/docs/resources/message#embed-object) messages with:
- A color-coded sidebar (blue for INFO, yellow for WARN, red for ERROR)
- A title with emoji and severity level
- A description with your `text`
- A footer with the project name, run name, and step number
