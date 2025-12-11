# Contributed Clients

This folder contains **lightweight, open-source experiment tracking** clients for several languages: currently, Go, JavaScript, and Rust. These clients let you log experimental data to a Trackio dashboard hosted on [🤗 Hugging Face Spaces](https://huggingface.co/spaces) or running locally.

**Note:** These clients are contributed by the open-source community and are not maintained at the same level as the rest of the Python-based repo.

# Usage

The steps below show how to spin up a brand new Trackio Dashboard Space, and log metrics from multiple languages using the provided SDKs.


## 1. Create a Trackio Dashboard Space

You can launch your own dashboard in seconds:

Create Space:
https://huggingface.co/new-space?sdk=gradio&template=gradio-templates%2Ftrackio-dashboard

Once deployed, the iframed Space URL will be something like:
https://username-trackio-dashboard.hf.space (you can find the iframed URL by clicking the triple dot menu next to Settings and then clicking "Embed this Space")

## 2. Log from any client

Then, `cd` into this `contrib` directory and run the appropriate quickstart script for the language you are interested in:

----------------
Go Quickstart
----------------
export TRACKIO_SERVER_URL="https://your-space-url.hf.space"
export HF_TOKEN="hf_…"
export TRACKIO_PROJECT="go-quickstart"
export TRACKIO_RUN="go-run-1"

go run trackio-go/examples/quickstart

Internal calls:
c.Log(map[string]float64{"loss":0.5,"acc":0.8}, 0, "")
c.Log(map[string]float64{"loss":0.4,"acc":0.82}, 1, "")
c.Flush()


----------------
JavaScript Quickstart
----------------
export TRACKIO_SERVER_URL="https://your-space-url.hf.space"
export HF_TOKEN="hf_…"
export TRACKIO_PROJECT="js-quickstart"
export TRACKIO_RUN="js-run-1"

node trackio-js/examples/quickstart.mjs

Internal calls:
c.log({loss:0.9, acc:0.6}, 0)
c.log({loss:0.7, acc:0.72}, 1)
await c.flush()


----------------
Rust Quickstart
----------------
export TRACKIO_SERVER_URL="https://your-space-url.hf.space"
export HF_TOKEN="hf_…"
export TRACKIO_PROJECT="rs-quickstart"
export TRACKIO_RUN="rs-run-1"

cd trackio-rs && cargo run --example quickstart

Internal calls:
client.log(json!({"loss":0.90,"acc":0.60}), Some(0), None);
client.log(json!({"loss":0.75,"acc":0.68}), Some(1), None);
client.flush().expect("flush ok");


## 3. View in the Dashboard

1. Open your Space:
   https://vaibhav2507-trackio-dashboard.hf.space

2. Select:
   Project: go-quickstart / js-quickstart / rs-quickstart
   Run: go-run-1 / js-run-1 / rs-run-1

3. Open the "Metrics" tab:
   X-axis: step
   Y-axis: loss and acc

---

## 4. curl Reference 

```bash
curl -sS "$TRACKIO_SERVER_URL/api/healthz"
curl -sS "$TRACKIO_SERVER_URL/api/projects"

curl -sS -X POST "$TRACKIO_SERVER_URL/api/bulk_log" \
  -H "content-type: application/json" \
  -d '{
    "project":"rest-quickstart",
    "run":"rest-run-1",
    "metrics_list":[{"loss":0.9,"acc":0.6},{"loss":0.7,"acc":0.72}],
    "steps":[0,1]
  }'



## 5. Example: Trackio Dashboard on Hugging Face Spaces

This repository demonstrates Go, JS, and Rust clients logging to a live Trackio dashboard.

Live demo:
https://vaibhav2507-trackio-dashboard.hf.space

Template used:
Trackio Dashboard

Workflow:
1. Create your own dashboard Space from the template.
2. Set TRACKIO_SERVER_URL to your Space URL.
3. Set HF_TOKEN to your Hugging Face token with write access.
4. Log metrics from each client:

Go:
  export TRACKIO_SERVER_URL="https://vaibhav2507-trackio-dashboard.hf.space"
  go run trackio-go/examples/quickstart

JavaScript:
  export TRACKIO_SERVER_URL="https://vaibhav2507-trackio-dashboard.hf.space"
  node trackio-js/examples/quickstart.mjs

Rust:
  export TRACKIO_SERVER_URL="https://vaibhav2507-trackio-dashboard.hf.space"
  cd trackio-rs && cargo run --example quickstart


Summary Table
-------------

Language | File                       | Command                          | Example Project
---------|-----------------------------|----------------------------------|------------------
Go       | trackio-go/examples/quickstart/main.go | go run trackio-go/examples/quickstart     | go-quickstart
JS       | trackio-js/examples/quickstart.mjs     | node trackio-js/examples/quickstart.mjs     | js-quickstart
Rust     | trackio-rs/examples/quickstart.rs | cd trackio-rs && cargo run --example quickstart | rs-quickstart

All clients log to the same Trackio dashboard in real time.

---

**Credit:** [@vaibhav2507](https://huggingface.co/vaibhav2507)

