# Trackio Dashboard – Multi-Language Quickstart

Trackio provides a **lightweight, open-source experiment tracker** for any language — Go, JavaScript, or Rust — using a simple REST API and a Gradio-powered dashboard hosted on [🤗 Hugging Face Spaces](https://huggingface.co/spaces).

This example shows how to spin up a brand new **Trackio Dashboard Space**, and log metrics from multiple languages using the provided SDKs.

---

## 1. Create a Trackio Dashboard Space

You can launch your own dashboard in seconds:

**[Create new Space](https://huggingface.co/new-space?sdk=gradio&template=gradio-templates%2Ftrackio-dashboard)**

That link will open a preconfigured template (`gradio-templates/trackio-dashboard`) which already exposes the REST endpoints:

| Endpoint | Description |
|-----------|-------------|
| `/api/healthz` | health check |
| `/api/projects` | list projects |
| `/api/runs/{project}` | list runs |
| `/api/logs/{project}/{run}` | get logs |
| `/api/bulk_log` | post metrics in bulk |

Once deployed, your Space URL (for example) might look like:
```
https://username-trackio-dashboard.hf.space
```

---

## 2. Log from any client

Each client SDK can talk to the dashboard via REST.  
Just set `TRACKIO_SERVER_URL` to your Space URL.

### Go Example

```bash
export TRACKIO_SERVER_URL="https://username-trackio-dashboard.hf.space"
export TRACKIO_PROJECT="go-quickstart"
export TRACKIO_RUN="go-run-1"

go run ./examples/quickstart
```

➡️ Internally it calls:
```go
c.Log(map[string]float64{"loss": 0.5, "acc": 0.8}, 0, "")
c.Log(map[string]float64{"loss": 0.4, "acc": 0.82}, 1, "")
c.Flush()
```

---

### JavaScript Example

```bash
export TRACKIO_SERVER_URL="https://username-trackio-dashboard.hf.space"
export TRACKIO_PROJECT="js-quickstart"
export TRACKIO_RUN="js-run-1"

node examples/quickstart.mjs
```

➡️ Internally it calls:
```js
c.log({ loss: 0.9, acc: 0.6 }, 0)
c.log({ loss: 0.7, acc: 0.72 }, 1)
await c.flush()
```

---

### Rust Example

```bash
export TRACKIO_SERVER_URL="https://username-trackio-dashboard.hf.space"
export TRACKIO_PROJECT="rs-quickstart"
export TRACKIO_RUN="rs-run-1"

cargo run --example quickstart
```

➡️ Internally it calls:
```rust
client.log(json!({"loss": 0.90, "acc": 0.60}), Some(0), None);
client.log(json!({"loss": 0.75, "acc": 0.68}), Some(1), None);
client.flush().expect("flush ok");
```

---

## 3. View in the Dashboard

1. Open your Space URL  
   → e.g. `https://username-trackio-dashboard.hf.space`  
2. Click **↻ Refresh Projects**
3. Select your project (`go-quickstart`, `js-quickstart`, or `rs-quickstart`)
4. Open the **Metrics** tab  
   - X-axis: `step`
   - Y-metrics: check `loss`, `acc`

You’ll see your metrics plotted live, backed by JSONL logs stored in the Space.

---

## 4. API Reference (minimal REST)

```bash
curl -sS "$TRACKIO_SERVER_URL/api/healthz"
curl -sS "$TRACKIO_SERVER_URL/api/projects"
curl -sS -X POST "$TRACKIO_SERVER_URL/api/bulk_log"   -H "content-type: application/json"   -d '{
    "project":"rest-quickstart",
    "run":"rest-run-1",
    "metrics_list":[{"loss":0.9,"acc":0.6},{"loss":0.7,"acc":0.72}],
    "steps":[0,1]
  }'
```

---

## 5. Implementation Notes

- Backend uses **FastAPI** with **Gradio Blocks UI** mounted on `/`
- Metrics are persisted as `JSONL` files under `~/.cache/huggingface/trackio/{project}/{run}.jsonl`
- Works seamlessly in Hugging Face Spaces (Docker or Gradio SDK)
- OAuth is automatically handled when deployed with `hf_oauth: true`

---

## 6. Example: Trackio Dashboard on Hugging Face Spaces

This repository demonstrates how Go, JavaScript, and Rust clients log to a live Trackio dashboard hosted on Hugging Face Spaces.
	•	Live demo: https://vaibhav2507-trackio-dashboard.hf.space￼
	•	Template used: Trackio Dashboard (Gradio template)￼

How this example works
	1.	Create your own dashboard Space from the template above (Docker or Gradio SDK).
	2.	Set TRACKIO_SERVER_URL to your Space URL (for example: https://vaibhav2507-trackio-dashboard.hf.space).
	3.	Log metrics from each client:

```
# Go
export TRACKIO_SERVER_URL="https://vaibhav2507-trackio-dashboard.hf.space"
go run ./examples/quickstart

# JavaScript
export TRACKIO_SERVER_URL="https://vaibhav2507-trackio-dashboard.hf.space"
node examples/quickstart.mjs

# Rust
export TRACKIO_SERVER_URL="https://vaibhav2507-trackio-dashboard.hf.space"
cargo run --example quickstart
```

## Summary

| Language | File | Command | Example Project |
|-----------|------|----------|-----------------|
| Go | `examples/quickstart.go` | `go run ./examples/quickstart` | go-quickstart |
| JavaScript | `examples/quickstart.mjs` | `node examples/quickstart.mjs` | js-quickstart |
| Rust | `examples/quickstart.rs` | `cargo run --example quickstart` | rs-quickstart |

Once deployed, all clients log to the same Trackio dashboard in real time.

---

**Maintainer:** [@vaibhav-research](https://huggingface.co/vaibhav2507)
License: Apache-2.0
