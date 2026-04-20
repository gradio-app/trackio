<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="trackio/assets/trackio_logo_type_dark_transparent.png">
  <source media="(prefers-color-scheme: light)" srcset="trackio/assets/trackio_logo_type_light_transparent.png">
  <img width="75%" alt="Trackio Logo" src="trackio/assets/trackio_logo_type_light_transparent.png">
</picture>
  
</p>


<div align="center">


  
[![trackio-backend](https://github.com/gradio-app/trackio/actions/workflows/test.yml/badge.svg)](https://github.com/gradio-app/trackio/actions/workflows/test.yml)
[![PyPI downloads](https://img.shields.io/pypi/dm/trackio)](https://pypi.org/project/trackio/)
[![PyPI](https://img.shields.io/pypi/v/trackio)](https://pypi.org/project/trackio/)
![Python version](https://img.shields.io/badge/python-3.10+-important)
[![Twitter follow](https://img.shields.io/twitter/follow/trackioapp?style=social&label=follow)](https://twitter.com/trackioapp)

</div>

Welcome to `trackio`: a lightweight, <u>free</u> experiment tracking library built by Hugging Face for humans and AI agents 🤗. 

**Why Trackio when other experiment-tracking libraries exist?** Trackio has a few qualities that make it particularly useful for  agents: 
* It is local-first, because you shouldn't need to make an account to log data
* Logs are stored in SQLite database (with support for "freezing" logs to Parquet), which not only lets Trackio supports very high throughputs for parallel experiments, but also
* provides an easy CLI interface for querying data (including directly on the SQL data), perfect for LLM-driven analysis.

So whether you are using agents to run entire research experiments autonomously or whether you are just using LLMs to analyze data, Trackio is for you.

For human users, Trackio _also_ ships with a Gradio-inspired dashboard so you can view metrics, media, tables, alerts, etc.:



https://github.com/user-attachments/assets/2683cf27-7520-4fff-9ee9-bdc08a8ca404



### Trackio's main features:

- **API compatible** with `wandb.init`, `wandb.log`, and `wandb.finish`. Drop-in replacement: just 

  ```python
  import trackio as wandb
  ```
  and keep your existing logging code.

- **Local-first, cloud-optional** design: dashboard runs locally by default. But note that you can also log metrics to a Hugging Face Space with `space_id` which is _also_ free and useful for collaborative experiments.
- **LLM-friendly**: Built with autonomous ML experiments in mind, Trackio includes a CLI for programmatic access and a Python API for run management, making it easy for LLMs to log metrics and query experiment data.
  - Use `trackio query project --project <name> --sql "SELECT ..."` for read-only SQL when `trackio list` and `trackio get` are not enough
  - See the storage schema and direct query reference at https://huggingface.co/docs/trackio/storage_schema

- **Free**: Everything here, including hosting on Hugging Face, is free!

Trackio is designed to be lightweight and _forkable_: **Python** for the backend and API, **Svelte 5** for the dashboard, so developers can fork the repository and extend either side.

## Installation

Trackio requires [Python 3.10 or higher](https://www.python.org/downloads/). Install with `pip`:

```bash
pip install trackio
```

or with `uv`:

```bash
uv pip install trackio
```

## Usage

To get started, you can run a simple example that logs some fake training metrics:

```python
import trackio
import random
import time

runs = 3
epochs = 8


for run in range(runs):
    trackio.init(
        project="my-project",
        config={"epochs": epochs, "learning_rate": 0.001, "batch_size": 64}
    )

    for epoch in range(epochs):
        train_loss = random.uniform(0.2, 1.0)
        train_acc = random.uniform(0.6, 0.95)

        val_loss = train_loss - random.uniform(0.01, 0.1)
        val_acc = train_acc + random.uniform(0.01, 0.05)

        trackio.log({
            "epoch": epoch,
            "train_loss": train_loss,
            "train_accuracy": train_acc,
            "val_loss": val_loss,
            "val_accuracy": val_acc
        })

        time.sleep(0.2)

trackio.finish()
```

Running the above will print to the terminal instructions on launching the dashboard.

The usage of `trackio` is designed to be identical to `wandb` in most cases, so you can easily switch between the two libraries.

```py
import trackio as wandb
```

## Dashboard

You can launch the dashboard by running in your terminal:

```bash
trackio show
```

or, in Python:

```py
import trackio

trackio.show()
```

You can also provide an optional `project` name as the argument to load a specific project directly:

```bash
trackio show --project "my-project"
```

or, in Python:

```py
import trackio 

trackio.show(project="my-project")
```

## Deploying to Hugging Face Spaces

When calling `trackio.init()`, by default the service will run locally and store project data on the local machine.

But if you pass a `space_id` to `init`, like:

```py
trackio.init(project="my-project", space_id="orgname/space_id")
```

or

```py
trackio.init(project="my-project", space_id="username/space_id")
```

it will use an existing or automatically deploy a new Hugging Face Space as needed. You should be logged in with the `huggingface-cli` locally and your token should have write permissions to create the Space.

## Self-hosted Trackio server

You can run the Trackio dashboard and API on your own machine or infrastructure and point training jobs at it over HTTP. Pass the write-access URL from `trackio.show()` (which may include `write_token` in the query), or a base URL plus the `TRACKIO_WRITE_TOKEN` environment variable. The client sends that token on requests; it is not your Hugging Face token.

```py
trackio.init(project="my-project", server_url="http://127.0.0.1:7860?write_token=YOUR_TOKEN")
```

You can also set `TRACKIO_SERVER_URL` (and optionally `TRACKIO_WRITE_TOKEN` if the URL has no query string). If `space_id` / `TRACKIO_SPACE_ID` and `server_url` / `TRACKIO_SERVER_URL` are both set, Trackio uses the Hugging Face Space and ignores the self-hosted URL.

See the documentation: [Self-host the Server](https://huggingface.co/docs/trackio/self_hosted_server).

## Syncing Offline Projects to Spaces

If you've been tracking experiments locally and want to move them to Hugging Face Spaces for sharing or collaboration, use the `sync` function:

```py
import trackio

trackio.sync(project="my-project", space_id="username/space_id")
```

This uploads your local project database to a new or existing Space. The Space will display all your logged experiments and metrics.

**Example workflow:**

```py
import trackio

# Start tracking locally
trackio.init(project="my-project", config={"lr": 0.001})
trackio.log({"loss": 0.5})
trackio.finish()

# Later, sync to Spaces
trackio.sync(project="my-project", space_id="username/my-experiments")
```

## Embedding a Trackio Dashboard

One of the reasons we created `trackio` was to make it easy to embed live dashboards on websites, blog posts, or anywhere else you can embed a website.

![image](https://github.com/user-attachments/assets/77f1424b-737b-4f04-b828-a12b2c1af4ef)

If you are hosting your Trackio dashboard on Spaces, then you can embed the url of that Space as an IFrame. You can even use query parameters to only specific projects and/or metrics, e.g.

```html
<iframe src="https://abidlabs-trackio-1234.hf.space/?project=my-project&metrics=train_loss,train_accuracy&sidebar=hidden" style="width:1600px; height:500px; border:0;">
```

Supported query parameters:

- `project`: (string) Open the dashboard on this project only. The project picker is hidden and the selection cannot be changed while this parameter is present (useful for embeds). The alias `selected_project` is accepted for the same behavior.
- `metrics`: (comma-separated list) Show only metrics whose names match exactly (after splitting on commas), e.g. `train_loss,train_accuracy`. Applied as the metrics filter on the Metrics page.
- `sidebar`: (string) One of `hidden`, `collapsed`, or omitted (default). **`hidden`** removes the sidebar entirely (full-width content; no rail). **`collapsed`** starts with the sidebar collapsed to the narrow rail; the user can expand it. By default the sidebar is open.
- `footer`: (string: "false"). When set to "false", hides the Gradio footer (Gradio-hosted Spaces). By default, the footer is visible.
- `xmin` / `xmax`: (numbers, use both together) Set the initial horizontal zoom range on the Metrics plots (shared x-axis window). Both must be valid numbers with `xmin < xmax`.
- `smoothing`: (number) Set the initial value of the smoothing slider (0-20, where 0 = no smoothing).
- `accordion`: (string: "hidden"). When set to "hidden", hides the section header accordions around metric groups. By default, section headers are visible.
- `theme`: (string) Dashboard theme, e.g. `light` or `dark` (see theme behavior in the app).
- `write_token`: (string) One-time token written to a cookie for write access on Hugging Face Spaces deployments; stripped from the URL after load.

## Alerts

Trackio supports alerts that let you flag important events during training. Alerts are printed to the terminal, stored in the database, displayed in the dashboard, and optionally sent to webhooks (Slack, Discord, or any URL).

```python
import trackio

trackio.init(
    project="my-project",
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
    webhook_min_level=trackio.AlertLevel.WARN,
)

for epoch in range(100):
    loss = train(...)
    trackio.log({"loss": loss})

    if epoch > 10 and loss > 5.0:
        trackio.alert(
            title="Loss spike",
            text=f"Loss jumped to {loss:.2f} at epoch {epoch}",
            level=trackio.AlertLevel.ERROR,
        )

trackio.finish()
```

You can query alerts via the CLI (`trackio get alerts --project "my-project" --json`), the Python API (`trackio.Api().alerts("my-project")`), or the HTTP endpoint (`/get_alerts`). For full details, see the [Alerts guide](https://huggingface.co/docs/trackio/alerts) and the [ML Agents guide](https://huggingface.co/docs/trackio/ml_agents).

## Examples

To get started and see basic examples of usage, see these files:

- [Basic example of logging metrics locally](https://github.com/gradio-app/trackio/blob/main/examples/fake-training.py)
- [Deploying the dashboard to Spaces](https://github.com/gradio-app/trackio/blob/main/examples/deploy-on-spaces.py)

## Throughput & Rate Limits

### Local logging

`trackio.log()` is a non-blocking call that appends to an in-memory queue and returns immediately. A background thread drains the queue every **0.5 s** and writes to the local SQLite database. Because log calls never touch the network or disk on the calling thread, the client-side throughput is effectively **unlimited** -- you can burst thousands of calls per second without slowing down your training loop.

Trackio is written defensively so Trackio-side failures should never take down your main experiment code. Under normal usage, issues inside Trackio's logging, flushing, or delivery paths degrade to warnings and local buffering rather than exceptions from your training loop.

### Logging to a Hugging Face Space

When a `space_id` is provided, the same background thread batches queued entries and pushes them to the Space via the Gradio client API. The main factors that affect end-to-end throughput are:

| Metric | Measured | Notes |
|---|---|---|
| **Burst from a single run** | **2,000 logs delivered in < 8 s** | `log()` calls themselves complete in ~0.01 s; the rest is network drain time. |
| **Parallel runs (32 threads)** | **32,000 logs (32 × 1,000) delivered in ~14 s wall time** | Each thread opens its own Gradio client connection to the Space. |
| **Logs per batch** | No hard cap | All entries queued during the 0.5 s interval are sent in a single `predict()` call. |
| **Data safety** | Zero-loss | If a batch fails to send, it is persisted to local SQLite and retried automatically when the connection recovers. |

These numbers were measured against a free-tier Hugging Face Space (2 vCPU / 16 GB RAM). Throughput will scale with the Space hardware tier, and local-only logging is orders of magnitude faster since no network round-trip is involved.

> **Tip:** For high-frequency logging (e.g. logging every training step), Trackio's queue-and-batch design means your training loop is never blocked by network I/O. Even if the Space is temporarily unreachable, logs accumulate locally and are replayed once the connection is restored.

## Note: Trackio is in Beta (DB Schema May Change)

Note that Trackio is in pre-release right now and we may release breaking changes. In particular, the schema of the Trackio sqlite database may change. Newer Trackio databases now use a stable `run_id` plus a non-unique `run_name`, while older databases remain readable in compatibility mode by treating `run_name` as the effective run identifier. Existing database files are located by default at: `~/.cache/huggingface/trackio`.  

The current SQLite and parquet layout is documented in the [Storage Schema and Direct Queries](https://huggingface.co/docs/trackio/storage_schema) guide, including examples for `trackio query`.

Since Trackio is in beta, your feedback is welcome! Please create issues with bug reports or feature requests.

## License

MIT License

## Documentation

The complete documentation and API reference for each version of Trackio can be found at: https://huggingface.co/docs/trackio/index

## Contribute

We welcome contributions to Trackio! Whether you're fixing bugs, adding features, or improving documentation, your contributions help make Trackio better for the entire machine learning community.

<p align="center">
  <img src="https://contrib.rocks/image?repo=gradio-app/trackio" />
</p>

To start contributing, see our [Contributing Guide](CONTRIBUTING.md).

### Development Setup

To set up Trackio for development, clone this repo and run:

```bash
pip install -e ".[dev,tensorboard]"
```

## Forking Trackio

Trackio is designed to be extremely forkable. The codebase is **not** Python-only: the **backend** lives in Python (SQLite, Gradio API, CLI), and the **dashboard** is **Svelte 5** under `trackio/frontend/` (with a production build bundled into the Python package). UI controls that mirror Gradio are implemented using **Gradio’s component source** as a starting point. You can fork the repo, change Python, frontend, or both (e.g. new dashboard pages, metrics, API routes), and see updates when running locally after installing in editable mode and rebuilding the frontend where needed.

If you deploy your Trackio dashboard to Hugging Face Spaces (by setting a `space_id` in `trackio.init()`), the Space UI reflects **your** checkout of Trackio—including any changes to the Python backend and the built Svelte assets.

To get started, follow the [Contributing Guide](#CONTRIBUTING.md) instructions to set up Trackio locally, then make your changes and run `trackio show` to preview them locally.

## Pronunciation

Trackio is pronounced TRACK-yo, as in "track yo' experiments"
