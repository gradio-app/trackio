# Environment Variables

Trackio uses environment variables to configure various aspects of its behavior, particularly for deployment to Hugging Face Spaces and dataset persistence. This guide covers the main environment variables and their usage.

## Core Environment Variables

### TRACKIO_SPACE_ID

Sets the Hugging Face Space ID for deploying your Trackio dashboard. This is useful when you want to automatically deploy to a specific Space without passing it to `trackio.init()`.

```bash
export TRACKIO_SPACE_ID="username/space_id"
```

Or in Python:

```python
import os
os.environ["TRACKIO_SPACE_ID"] = "username/space_id"
```

**Usage:** When set, Trackio will automatically deploy dashboards to the specified Hugging Face Space. The Space will be created if it doesn't exist (requires appropriate HF token permissions).

**Integration with Transformers/TRL:** When using the Transformers `Trainer` or TRL with `TrainingArguments(report_to="trackio")`, this environment variable will be used to determine where to deploy the dashboard. This allows you to set up Space deployment once and have all your training runs automatically use it.

**Note:** This is particularly useful in automated environments like CI/CD pipelines or when using Trackio with the Transformers Trainer.

### TRACKIO_PROJECT_NAME

Specifies the default project name for logging experiments.

```bash
export TRACKIO_PROJECT_NAME="my-project"
```

Or in Python:

```python
import os
os.environ["TRACKIO_PROJECT_NAME"] = "my-project"
```

**Usage:** Commonly used with the Transformers Trainer integration to set the project name without modifying training code.

### TRACKIO_DATASET_ID

Sets the Hugging Face Dataset ID where logs will be stored when running on Hugging Face Spaces.

```bash
export TRACKIO_DATASET_ID="username/dataset_name"
```

**Usage:** Trackio automatically uses this to persist logs to a Hugging Face Dataset when deployed on Spaces. This is typically set automatically when deploying to Spaces.

### HF_TOKEN

Your Hugging Face authentication token.

```bash
export HF_TOKEN="hf_xxxxxxxxxxxxx"
```

**Usage:** Required for creating Spaces and Datasets on Hugging Face. Set this locally when deploying to Spaces from your machine.

### TRACKIO_DIR

Specifies a custom directory for storing Trackio data (primarily used for testing).

```bash
export TRACKIO_DIR="/path/to/trackio/data"
```

**Usage:** Mainly used in testing environments. By default, Trackio stores data in `~/.cache/huggingface/trackio/`.

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

## Best Practices

1. **Security**: Never commit environment variables containing tokens or secrets to version control. Use secret management tools or `.env` files (added to `.gitignore`).

2. **Space IDs**: Use the format `username/space_name` or `organization/space_name` for Space IDs.

3. **Precedence**: Environment variables can be overridden by explicit parameters passed to `trackio.init()`.

4. **Automation**: Use environment variables to configure Trackio in automated environments without modifying code.

## Troubleshooting

If your dashboard is not deploying to Spaces:
- Ensure `HF_TOKEN` is set and has write permissions
- Verify `TRACKIO_SPACE_ID` follows the correct format
- Check that you're logged in with `huggingface-cli login`

For more information, see the [Deploy and Embed Dashboards](deploy_embed.md) guide.