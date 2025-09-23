# Environment Variables

Trackio uses environment variables to configure various aspects of its behavior, particularly for deployment to Hugging Face Spaces and dataset persistence. This guide covers the main environment variables and their usage.

## Core Environment Variables

### `TRACKIO_DIR`

Specifies a custom directory for storing Trackio data. By default, Trackio stores data in `~/.cache/huggingface/trackio/`.

```bash
export TRACKIO_DIR="/path/to/trackio/data"
```

### `TRACKIO_DATASET_ID`

Sets the Hugging Face Dataset ID where logs will be stored when running on Hugging Face Spaces. If not provided, the dataset name will be set automatically when deploying to Spaces.


```bash
export TRACKIO_DATASET_ID="username/dataset_name"
```

### `HF_TOKEN`

Your Hugging Face authentication token. Required for creating Spaces and Datasets on Hugging Face. Set this locally when deploying to Spaces from your machine. Must have `write` permissions for the namespace that you are deploying the Trackio dashboard.

```bash
export HF_TOKEN="hf_xxxxxxxxxxxxx"
```


## Gradio Environment Variables

Since Trackio is built on top of Gradio, you can use environment variables used by Gradio to control the behavior of Trackio. Here are a few examples:


### `GRADIO_SERVER_PORT`

Specifies the port on which the Tradio dashboard will launch. Defaults to `7860`

```bash
export GRADIO_SERVER_PORT=8000
```

### `GRADIO_SERVER_NAME`

Defines the host name for the Trackio dashboard server. To make the dasbhoard accessible from any IP address, set this to `"0.0.0.0"`

```bash
export GRADIO_SERVER_NAME="0.0.0.0"
```

### `GRADIO_MCP_SERVER`

Enables the MCP (Model Context Protocol) server functionality in Trackio. When enabled, the Trackio dashboard will be set up as an MCP server and certain functions will be exposed as MCP tools that can be used by LLMs (e.g. to read the logged metrics).

```bash
export GRADIO_MCP_SERVER="True"
```



See [this more comprehensive list](https://www.gradio.app/guides/environment-variables) of environment variables used by Gradio.


