# trackio-go

[![Go Reference](https://pkg.go.dev/badge/github.com/gradio-app/trackio/contrib/go.svg)](https://pkg.go.dev/github.com/gradio-app/trackio/contrib/go)

The official Go SDK for [Trackio](https://github.com/gradio-app/trackio).

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
export TRACKIO_PROJECT="go-quickstart"
export TRACKIO_RUN="go-run-1"

go run ./examples/quickstart
```

### 3. View in the Dashboard

Open your Space URL and select:
- Project: `go-quickstart`
- Run: `go-run-1`

Open the "Metrics" tab to view your logged metrics.

## Usage

```go
c := trackio.New(
  trackio.WithBaseURL("https://your-space-url.hf.space"),
  trackio.WithProject("my-project"),
  trackio.WithRun("my-run"),
)

c.Log(map[string]float64{"loss": 0.5, "acc": 0.8}, 0, "")
c.Log(map[string]float64{"loss": 0.4, "acc": 0.82}, 1, "")
c.Flush(context.Background())
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TRACKIO_SERVER_URL` | Base Trackio server URL | `http://127.0.0.1:7860` |
| `TRACKIO_PROJECT` | Project name | - |
| `TRACKIO_RUN` | Run name | - |
| `HF_TOKEN` | Hugging Face token with write access | - |

## Install

```bash
go get github.com/gradio-app/trackio/contrib/trackio-go
```
