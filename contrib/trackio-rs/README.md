# trackio-rs — Rust client for Trackio

Tiny, dependency-light client-only SDK to log metrics from Rust programs into a local or remote Trackio dashboard.
- Works with the Trackio UI you run locally via Python
- Auto-discovers the correct REST path (/api/bulk_log or /gradio_api/bulk_log)
- Buffered + batched logging with manual flush()
- No server code — just a thin HTTP client
- Includes a quickstart example

## Prereqs

You need a Trackio dashboard running somewhere (local or remote). For local dev:
- Python 3.9+
- pip install trackio
- Important: run Trackio with its REST API enabled.

## Install

Option A: Use as a crate (published later)

```bash
cargo add trackio
```

Option B: Path dependency (while iterating locally)

In your project’s Cargo.toml:

```bash
[dependencies]
trackio = { path = "../trackio-rs" }  # adjust the path to this folder
```


## Run the Trackio UI locally

- Start Trackio and expose its API:

```bash
export TRACKIO_SHOW_API=1
python -c "import trackio; trackio.init(project='rs-quickstart', embed=False); import time; time.sleep(9999)"
```

- On startup you should see:

```bash
* Trackio REST API mounted at /api/*
* Trackio project initialized: rs-quickstart
```

The UI will be at http://127.0.0.1:7860.
You can later open it directly filtered to your project:

```bash
http://127.0.0.1:7860/?selected_project=rs-quickstart
```


## Quickstart

### Example program

```bash
use trackio::Client;
use serde_json::json;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // You can also set TRACKIO_SERVER_URL, TRACKIO_PROJECT, TRACKIO_RUN in the env (see below)
    let client = Client::new()
        .with_base_url("http://127.0.0.1:7860")
        .with_project("rs-quickstart")
        .with_run("rs-run-1");

    // log a few points
    client.log(json!({ "loss": 0.5, "acc": 0.8 }), Some(0), None);
    client.log(json!({ "loss": 0.4, "acc": 0.82 }), Some(1), None);

    // push the batch
    client.flush()?;
    println!("flushed. open dashboard to see metrics.");

    Ok(())
}
```

Run it

If you used this repo’s example:

```bash
# From trackio-rs/
cargo run --example quickstart
```

You should see:

```bash
flushed. open dashboard to see metrics.
```

Open the UI:

```bash
http://127.0.0.1:7860/?selected_project=rs-quickstart
```

## API

```bash
pub struct Client { /* … */ }

impl Client {
  /// Creates a client reading env defaults (see below).
  pub fn new() -> Self;

  /// Set base URL like "http://127.0.0.1:7860".
  pub fn with_base_url(self, u: &str) -> Self;

  /// Set Trackio project name.
  pub fn with_project(self, p: &str) -> Self;

  /// Set run name.
  pub fn with_run(self, r: &str) -> Self;

  /// Queue metrics into an in-memory buffer.
  /// - `metrics`: arbitrary JSON object (serde_json::Value)
  /// - `step`: optional i64 step (use None for auto/sequential)
  /// - `timestamp`: optional RFC3339 (or pass None to let the server fill)
  pub fn log(&self, metrics: serde_json::Value, step: Option<i64>, timestamp: Option<String>);

  /// Synchronously flushes the current buffer via HTTP.
  pub fn flush(&self) -> Result<(), TrackioError>;
}

#[derive(thiserror::Error, Debug)]
pub enum TrackioError {
    NoBulkEndpoint,               // Neither /api/bulk_log nor /gradio_api/bulk_log is available
    Http(reqwest::Error),         // Network errors
    NotFound(String),             // 404 with body message
    Status(u16, String),          // Other HTTP status with body
}

```


- Logging is buffered in memory; nothing is sent until flush().
- The payload is sent as Trackio’s bulk_log format

```bash
{
  "project": "...",
  "run": "...",
  "metrics_list": [ { ... }, { ... } ],
  "steps": [ 0, 1 ],
  "timestamps": [ "", "" ]
}
```


## Environment variables

All are optional (you can set via .with_* instead):

Variable	                    Purpose	                                        Default
TRACKIO_SERVER_URL	            Base URL of the dashboard	                    http://127.0.0.1:7860
TRACKIO_PROJECT	                Default project name	                        ""
TRACKIO_RUN	                    Default run name	                            ""
TRACKIO_WRITE_TOKEN	            Future use (if server enforces write tokens)	unset
TRACKIO_TIMEOUT_MS	            HTTP client timeout (ms)	                    5000
TRACKIO_MAX_BATCH	            Buffer size before auto-flush attempt in log()	128


## How it works
- We call Trackio’s bulk logging endpoint.
- The client auto-discovers which path exists on the server once per process:
	1.	Try POST /api/bulk_log
	2.	Else try POST /gradio_api/bulk_log
	3.	Cache the working path for the rest of the run
- If neither exists, you’ll get TrackioError::NoBulkEndpoint — this usually means your server wasn’t started with TRACKIO_SHOW_API=1.


## Developing

Run example:

```bash
cargo run --example quickstart
```

Run tests (if/when added):

```bash
cargo test
```

Lint/format:

```bash
cargo fmt
cargo clippy
```


## Roadmap / nice-to-haves
- Optional auto-flush background thread honoring TRACKIO_FLUSH_INTERVAL_MS
- Async client (reqwest async feature)
- Attach write token header once the server enforces it
- Media/table helpers to mirror Trackio Python convenience types

