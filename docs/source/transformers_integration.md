# Transformers Integration

Trackio integrates natively with Transformers so you can log metrics with minimal setup. Ensure you have the latest version of `transformers` installed (version 4.54.0 or higher).

```python
import numpy as np
from datasets import Dataset
from transformers import Trainer, AutoModelForCausalLM, TrainingArguments

# Create a fake dataset
data = np.random.randint(0, 1000, (8192, 64)).tolist()
dataset = Dataset.from_dict({"input_ids": data, "labels": data})

# Train a model using the Trainer API
trainer = Trainer(
    model=AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-0.6B"),
    args=TrainingArguments(run_name="Qwen3-0.6B-training", report_to="trackio"),
    train_dataset=dataset,
)
trainer.train()
```

## Configuring Project and Space

You can specify your Trackio project name and space ID using environment variables:

```sh
export TRACKIO_PROJECT_NAME="my-project"
export TRACKIO_SPACE_ID="username/space_id"
```

Or set them directly in Python:

```python
import os

os.environ["TRACKIO_PROJECT_NAME"] = "my-project"
os.environ["TRACKIO_SPACE_ID"] = "username/space_id"

# rest of your code...
```

<iframe 
    src="https://trackio-documentation.hf.space/?project=transformers-integration&sidebar=hidden" 
    style="width: 100%; border:0;" 
    height="1530">
</iframe>