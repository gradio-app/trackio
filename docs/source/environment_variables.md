# Environment Variables

Trackio uses environment variables to configure various aspects of its behavior, particularly for deployment to Hugging Face Spaces and dataset persistence. This guide covers the main environment variables and their usage.

## Core Environment Variables

### TRACKIO_SPACE_ID

Sets the Hugging Face Space ID for deploying your Trackio dashboard. This is useful when you want to automatically deploy to a specific Space without passing it to `trackio.init()`. The Space will be created if it doesn't exist (requires appropriate HF token permissions).

```bash
export TRACKIO_SPACE_ID="username/space_id"
```

Or in Python:

```python
import os
os.environ["TRACKIO_SPACE_ID"] = "username/space_id"
```

The username can be a personal Hugging Face account or an org account on Hugging Face.


**Integration with Transformers/TRL:** When using the Transformers `Trainer` or one of the Trainer classes in TRL with `TrainingArguments(report_to="trackio")`, this environment variable will be used to determine where to deploy the dashboard. This allows you to set up Space deployment once and have all your training runs automatically use it.

### TRACKIO_PROJECT_NAME

Specifies the default project name for logging experiments. This is useful when you want to set a specific project name without passing it to `trackio.init()`.

```bash
export TRACKIO_PROJECT_NAME="my-project"
```

Or in Python:

```python
import os
os.environ["TRACKIO_PROJECT_NAME"] = "my-project"
```


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


## Example Usage

### Local Development with Space Deployment

```bash
# Set up environment for local development with automatic Space deployment
export HF_TOKEN="hf_xxxxxxxxxxxxx"
export TRACKIO_SPACE_ID="myusername/my-trackio-dashboard"
export TRACKIO_PROJECT_NAME="my-ml-project"

# Now run your training script
python train.py
```

### Using with Transformers Trainer

```python
import os
from transformers import Trainer, TrainingArguments

# Configure Trackio for Transformers
os.environ["TRACKIO_PROJECT_NAME"] = "llm-finetuning"
os.environ["TRACKIO_SPACE_ID"] = "myorg/llm-experiments"

# Train with automatic Trackio logging
trainer = Trainer(
    model=model,
    args=TrainingArguments(
        run_name="experiment-1",
        report_to="trackio",  # Enable Trackio logging
        # ... other args
    ),
    train_dataset=train_dataset,
)
trainer.train()
```

### CI/CD Pipeline

```yaml
# GitHub Actions example
env:
  HF_TOKEN: ${{ secrets.HF_TOKEN }}
  TRACKIO_SPACE_ID: "myorg/ci-experiments"
  TRACKIO_PROJECT_NAME: "${{ github.ref_name }}"

steps:
  - name: Run experiments
    run: python experiments.py
```

## General notes

1. **Security**: Never commit environment variables containing tokens or secrets to version control. Use secret management tools or `.env` files (added to `.gitignore`).

2. **Space IDs**: Use the format `username/space_name` or `organization/space_name` for Space IDs.

3. **Precedence**: Environment variables can be overridden by explicit parameters passed to `trackio.init()`.

## Troubleshooting

If your dashboard is not deploying to Spaces:
- Ensure `HF_TOKEN` is set and has write permissions
- Verify `TRACKIO_SPACE_ID` follows the correct format
- Check that you're logged in with `huggingface-cli login`

