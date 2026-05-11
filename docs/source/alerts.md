# Alerts

Trackio alerts let you flag important events during a run. When an alert fires, it is:

1. **Printed to the terminal** with a color-coded severity label
2. **Stored in the database** so it can be queried later via the CLI, Python API, or HTTP endpoint
3. **Displayed in the dashboard** via a floating alert panel and the Reports page
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

---

## Metric Watchers

Watchers let you define rules upfront and have Trackio fire alerts automatically during training — no manual `trackio.alert()` calls needed. Every call to [`log`] checks all registered watchers and fires the appropriate alerts if a condition is met.

```python
import trackio

trackio.init(project="my-project")

trackio.watch("train/loss", nan=True, spike_factor=3.0, patience=100, max_value=50.0)
trackio.watch("val/accuracy", patience=200, min_delta=0.001, mode="max")

for step in range(1000):
    loss, val_acc = train_step()
    trackio.log({"train/loss": loss, "val/accuracy": val_acc}, step=step)
    if trackio.should_stop():
        break
```

Watcher-generated alerts are stored, displayed in the dashboard, and delivered to webhooks exactly like manually-fired alerts.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `metric` | `str` | *(required)* | The metric name to watch (e.g., `"train/loss"`). |
| `nan` | `bool` | `True` | Fire an ERROR alert if the value becomes NaN or Inf. |
| `spike_factor` | `float \| None` | `None` | Fire a WARN alert when `\|value − recent_avg\| > (spike_factor − 1) × \|recent_avg\|` (e.g., `3.0` triggers when the deviation exceeds 2× `\|avg\|`). Symmetric — drops trigger too. |
| `patience` | `int \| None` | `None` | Fire a WARN alert if no improvement is seen for this many log steps. Also sets `should_stop()` to `True`. |
| `min_delta` | `float` | `0.0` | Minimum change to count as an improvement (used with `patience`). |
| `max_value` | `float \| None` | `None` | Fire an ERROR alert if the value exceeds this threshold. Also sets `should_stop()` to `True`. |
| `min_value` | `float \| None` | `None` | Fire a WARN alert if the value drops below this threshold. |
| `window` | `int` | `5` | Number of recent values to average for spike detection. |
| `mode` | `"min" \| "max"` | `"min"` | Whether lower (`"min"`) or higher (`"max"`) values indicate improvement. Affects `patience`-based stagnation. |

### Conditions

#### NaN / Inf

Enabled by default (`nan=True`). Fires an **ERROR** alert and sets `should_stop()` to `True` the moment the metric becomes `NaN` or `Inf`.

```python
trackio.watch("train/loss", nan=True)
```

#### Max / Min Thresholds

`max_value` fires an **ERROR** alert (and stops) when the metric exceeds the threshold. `min_value` fires a **WARN** alert when it falls below, but — unlike `max_value` — does **not** set `should_stop()`. Each alert fires once when the threshold is crossed and resets if the value recovers.

```python
trackio.watch("train/loss", max_value=20.0)
trackio.watch("val/accuracy", min_value=0.5)
```

#### Spike Detection

Fires a **WARN** alert when the value deviates from the recent moving average by more than `(spike_factor - 1) × |recent_avg|` — that is, when `|value − recent_avg| > (spike_factor − 1) × |recent_avg|`. Detection is symmetric: sudden drops trigger the alert in addition to sudden rises. With `spike_factor=3.0` and a recent average of `1.0`, the alert fires once `|value − 1.0| > 2.0`. The alert resets automatically once the value returns to normal.

```python
trackio.watch("train/loss", spike_factor=3.0, window=10)
```

#### Stagnation

Fires a **WARN** alert (and sets `should_stop()` to `True`) when no improvement is seen for `patience` consecutive log steps. Set `mode="max"` for metrics where higher is better.

```python
trackio.watch("val/accuracy", patience=50, min_delta=0.001, mode="max")
```

### Early Stopping

[`should_stop`] returns `True` if any watcher has triggered a stop condition (NaN/Inf, `max_value` exceeded, `patience` exhausted, or a custom watcher returned `{"stop": True}`):

```python
for step in range(1000):
    trackio.log({"train/loss": loss}, step=step)
    if trackio.should_stop():
        print("Stopping early.")
        break
```

Watchers are cleared automatically when `trackio.init()` is called for a new run.

### Filtering Watcher Alerts Programmatically

Every watcher-generated alert includes a `data["reason"]` field you can match against `trackio.AlertReason` constants:

```python
alerts = trackio.Api().alerts("my-project", run="brave-sunset-0")

for alert in alerts:
    reason = (alert.get("data") or {}).get("reason")
    if reason == trackio.AlertReason.NAN_INF:
        print("NaN/Inf detected:", alert["title"])
    elif reason == trackio.AlertReason.STAGNATION:
        print("Stagnated:", alert["data"]["steps_without_improvement"], "steps")
```

| Constant | Value | Condition |
|---|---|---|
| `AlertReason.NAN_INF` | `"nan_inf"` | Metric became NaN or Inf |
| `AlertReason.MAX_EXCEEDED` | `"max_exceeded"` | Metric exceeded `max_value` |
| `AlertReason.MIN_EXCEEDED` | `"min_exceeded"` | Metric dropped below `min_value` |
| `AlertReason.SPIKE` | `"spike"` | Spike detected vs. recent average |
| `AlertReason.STAGNATION` | `"stagnation"` | No improvement for `patience` steps |
| `AlertReason.CUSTOM` | `"custom"` | Custom condition returned `True` |

### Custom Conditions

Pass `fn` to [`watch`] to define your own condition. The function receives `(value, step)` and should return `True` to fire a default WARN alert, a list of alert dicts for full control, or a falsy value for no alert:

```python
def check_divergence(value, step):
    if value > 50.0:
        return [
            {
                "title": "Loss diverged",
                "level": trackio.AlertLevel.ERROR,
                "text": f"val_loss={value:.2f} at step {step}",
                "data": {"reason": "diverged", "threshold": 50.0, "value": value},
                "stop": True,
            }
        ]
    return None

trackio.watch("val/loss", fn=check_divergence)
```

Include `"stop": True` in a returned dict to set `should_stop()` to `True`. Custom conditions can be combined with built-in ones — both run independently on every `log()` call:

```python
trackio.watch("train/loss", nan=True, fn=check_divergence)
```

---

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

Alerts appear in two places in the Trackio dashboard:

1. **Alert panel** — A floating panel in the bottom-right corner of every dashboard page. It shows all alerts (across all projects) that arrived since the dashboard was launched, with the latest alert at the bottom. You can filter by severity level and expand/collapse the panel. The panel flashes when new alerts arrive.

2. **Reports page** — The Reports page includes a full alerts table below the reports section. You can filter alerts by run (via the sidebar dropdown) and by severity level (via the sidebar checkbox group).

To launch the dashboard:

```bash
trackio show --project "my-project"
```

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

### Inspecting Metrics Around an Alert

When an alert fires, you often want to see what all the metrics looked like at that point. Use `trackio get snapshot` to get every metric at/around the alert's step or timestamp:

```bash
# An alert fired at step 200 — get all metrics in a ±5 step window
trackio get snapshot --project "my-project" --run "brave-sunset-0" --around 200 --window 5 --json

# Or inspect a single metric around the alert's timestamp
trackio get metric --project "my-project" --run "brave-sunset-0" --metric "loss" --at-time "2025-06-01T12:05:30" --window 60 --json
```

See the [CLI Commands](cli_commands) page for the full list of filtering options.

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
