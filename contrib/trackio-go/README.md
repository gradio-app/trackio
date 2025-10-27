# trackio-go — Go client for Trackio

A minimal Go client for [Trackio](https://github.com/gradio-app/trackio), the open-source experiment tracker built by Hugging Face.

## Install

```bash
go get github.com/gradio-app/trackio/contrib/trackio-go
```

## Quickstart
- Start the Trackio backend:

```bash
export TRACKIO_SHOW_API=1
python -c "import trackio; trackio.init(project='go-quickstart', embed=False); import time; time.sleep(9999)"
```

-  In another terminal:

```bash
go run ./examples/quickstart
```

You should see:

```bash
* Waiting for Trackio server at: http://127.0.0.1:7860
* Trackio REST detected at: http://127.0.0.1:7860/api/projects
* Logging sample metrics to: http://127.0.0.1:7860
* Flushing logs...
* Done. Check the Trackio dashboard.
```

## Environment Variables

Variable	                Description	                        Default
TRACKIO_SERVER_URL	        Base Trackio server URL	            http://127.0.0.1:7860
TRACKIO_PROJECT	            Project name	
TRACKIO_RUN	                Run name	
TRACKIO_WRITE_TOKEN	        Optional API token	
TRACKIO_MAX_BATCH	        Max batch size before auto-flush    128
TRACKIO_FLUSH_INTERVAL_MS	Flush interval	                    200

## Example

```bash
c := trackio.New(
  trackio.WithBaseURL("http://127.0.0.1:7860"),
  trackio.WithProject("go-demo"),
  trackio.WithRun("first-run"),
)

step := 0
c.Log(map[string]any{"loss": 0.42}, &step, "")
c.Flush(context.Background())
```

Run it locally:

```bash
go test ./...
```

## Lint & format

```bash
go fmt ./...
go vet ./...
golangci-lint run
```

