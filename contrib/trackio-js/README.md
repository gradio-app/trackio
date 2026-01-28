# trackio-js

[![npm version](https://img.shields.io/npm/v/trackio-client-js.svg)](https://www.npmjs.com/package/trackio-client-js)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/gradio-app/trackio/blob/main/LICENSE)

The official JavaScript/TypeScript client for [Trackio](https://github.com/gradio-app/trackio).

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
export TRACKIO_PROJECT="js-quickstart"
export TRACKIO_RUN="js-run-1"

node examples/quickstart.mjs
```

### 3. View in the Dashboard

Open your Space URL and select:
- Project: `js-quickstart`
- Run: `js-run-1`

Open the "Metrics" tab to view your logged metrics.

## Usage

```javascript
import { TrackioClient } from './src/client.js';

const client = new TrackioClient({
  baseUrl: 'https://your-space-url.hf.space',
  project: 'my-project',
  run: 'my-run',
});

client.log({ loss: 0.9, acc: 0.6 }, 0);
client.log({ loss: 0.7, acc: 0.72 }, 1);
await client.flush();
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
npm install
npm run build
```
