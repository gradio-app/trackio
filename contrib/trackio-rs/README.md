# trackio-rs

[![Crates.io](https://img.shields.io/crates/v/trackio-rs.svg)](https://crates.io/crates/trackio-rs)
[![Documentation](https://docs.rs/trackio-rs/badge.svg)](https://docs.rs/trackio-rs)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/gradio-app/trackio/blob/main/LICENSE)

**trackio-rs** is the high-performance Rust client for [Trackio](https://github.com/gradio-app/trackio), the open-source experiment tracker built by Hugging Face. 

This SDK enables systems engineers and ML researchers to log metrics from high-concurrency, production-grade environments with the safety and speed of Rust.

## Why trackio-rs?

While the Python client is ideal for research, **trackio-rs** is built for:
- **Production Systems**: Low-latency metric logging for live model monitoring.
- **Thread Safety**: Built on `parking_lot` and `reqwest` for safe concurrent logging.
- **Memory Efficiency**: Minimal footprint for edge devices and high-throughput servers.

## Quickstart

### 1. Set Up Your Dashboard
Deploy your Trackio Space on Hugging Face:
[Deploy Trackio Template](https://huggingface.co/new-space?sdk=gradio&template=gradio-templates%2Ftrackio-dashboard)

### 2. Installation
Add this to your `Cargo.toml`:

```toml
[dependencies]
trackio-rs = "0.1.0"
```

## Quickstart

### 1. Create a Trackio Dashboard Space

Create your dashboard Space:
https://huggingface.co/new-space?sdk=gradio&template=gradio-templates%2Ftrackio-dashboard

Once deployed, the iframed Space URL will be something like:
`https://username-trackio-dashboard.hf.space` (you can find the iframed URL by clicking the triple dot menu next to Settings and then clicking "Embed this Space")

### 2. Log metrics

Set environment variables and run the example:

```bash
export TRACKIO_SERVER_URL="https://your-space-url.hf.space"
export HF_TOKEN="hf_…"
export TRACKIO_PROJECT="rs-quickstart"
export TRACKIO_RUN="rs-run-1"

cargo run --example quickstart
```

### 3. View in the Dashboard

Open your Space URL and select:
- Project: `rs-quickstart`
- Run: `rs-run-1`

Open the "Metrics" tab to view your logged metrics.

## Usage

```rust
use trackio::Client;
use serde_json::json;

let client = Client::new()
    .with_base_url("https://your-space-url.hf.space")
    .with_project("my-project")
    .with_run("my-run");

client.log(json!({"loss": 0.5, "acc": 0.8}), Some(0), None);
client.log(json!({"loss": 0.4, "acc": 0.82}), Some(1), None);
client.flush()?;
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TRACKIO_SERVER_URL` | Base Trackio server URL | `http://127.0.0.1:7860` |
| `TRACKIO_PROJECT` | Project name | - |
| `TRACKIO_RUN` | Run name | - |
| `HF_TOKEN` | Hugging Face token with write access | - |

