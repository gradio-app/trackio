# trackio-js: JS client for Trackio

Tiny JavaScript/TypeScript client for Trackio.
It batches metrics and posts them to a locally running Trackio dashboard (or a Space) via HTTP.

## Quick start

1) Start Trackio locally (with REST API enabled)

```bash
python -c "import trackio; trackio.init(project='js-quickstart', embed=False); import time; time.sleep(9999)"
```
2) Install

```bash
npm install
npm run build
```

Run the example:

```bash
npm run example
```

You should see logs like:

```bash
* Waiting for Trackio server at: http://127.0.0.1:7860
* Trackio REST detected at: http://127.0.0.1:7860/api/projects
* Logging sample metrics to: http://127.0.0.1:7860
* Flushing logs...
* Done. Check the Trackio dashboard.
```

Open the dashboard in your browser:

```bash
http://127.0.0.1:7860/?selected_project=js-quickstart
```

## API

new TrackioClient(options?)

Option	                            Type	            Default
baseUrl	                            string	            process.env.TRACKIO_SERVER_URL → http://127.0.0.1:7860
project	                            string	            process.env.TRACKIO_PROJECT
run	                                string	            process.env.TRACKIO_RUN
writeToken	                        string	            process.env.TRACKIO_WRITE_TOKEN
timeoutMs	                        number	            process.env.TRACKIO_TIMEOUT_MS → 5000
maxBatch	                        number	            process.env.TRACKIO_MAX_BATCH → 128


Fluent setters are also available:
	•	.withBaseUrl(url: string)
	•	.withProject(project: string)
	•	.withRun(run: string)
	•	.withWriteToken(token: string)

client.log(metrics: object, step?: number, timestamp?: string)

Queues one log record.
	•	timestamp may be an empty string "" (server will accept it).

await client.flush()

Sends all queued metrics. The client:
	•	Auto-discovers the working endpoint on first call:
	•	tries POST /api/bulk_log, falls back to POST /gradio_api/bulk_log
	•	caches the working path for future flushes
	•	Sends payload like:


```bash
{
  "project": "js-quickstart",
  "run": "js-run-1",
  "metrics_list": [{"loss": 0.5}, {"loss": 0.4}],
  "steps": [0, 1],
  "timestamps": ["", ""]
}
```

## Environment variables

Name	                        Default	                    Notes
TRACKIO_SERVER_URL	            http://127.0.0.1:7860	    Where Trackio UI is running
TRACKIO_PROJECT	                —	                        Project name (optional)
TRACKIO_RUN	                    —	                        Run name (optional)
TRACKIO_WRITE_TOKEN	            —	                        optional write auth token
TRACKIO_TIMEOUT_MS	            5000	                    HTTP request timeout
TRACKIO_MAX_BATCH	            128	                        Max logs to buffer before flush




