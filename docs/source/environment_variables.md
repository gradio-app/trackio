# Environment Variables

Trackio uses environment variables to configure various aspects of its behavior, particularly for deployment to Hugging Face Spaces and dataset persistence. This guide covers the main environment variables and their usage.

## Core Environment Variables


### TRACKIO_DATASET_ID

Sets the Hugging Face Dataset ID where logs will be stored when running on Hugging Face Spaces. If not provided, the dataset name will be set automatically when deploying to Spaces.


```bash
export TRACKIO_DATASET_ID="username/dataset_name"
```

### HF_TOKEN

Your Hugging Face authentication token.

```bash
export HF_TOKEN="hf_xxxxxxxxxxxxx"
```

**Usage:** Required for creating Spaces and Datasets on Hugging Face. Set this locally when deploying to Spaces from your machine. Must have `write` permissions for the namespace that you are deploying the Trackio dashboard.

### TRACKIO_DIR

Specifies a custom directory for storing Trackio data. By default, Trackio stores data in `~/.cache/huggingface/trackio/`.

```bash
export TRACKIO_DIR="/path/to/trackio/data"
```


