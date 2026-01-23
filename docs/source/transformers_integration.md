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
    args=TrainingArguments(report_to="trackio", run_name="Qwen3-0.6B-training"),
    train_dataset=dataset,
)
trainer.train()
```

## Configuring Project and Space

Set the project and space ID directly in your `TrainingArguments`:

```python
from transformers import TrainingArguments

args = TrainingArguments(
    report_to="trackio",
    run_name="my-run",
    project="my-project",
    trackio_space_id="username/space_id",
)
```

<iframe 
    src="https://trackio-documentation.hf.space/?project=transformers-integration&sidebar=hidden" 
    style="width: 100%; border:0;" 
    height="1530">
</iframe>
