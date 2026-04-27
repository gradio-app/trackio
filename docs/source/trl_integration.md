# TRL Integration

Trackio integrates natively with [TRL](https://github.com/huggingface/trl) so you can log metrics from any TRL trainer (`SFTTrainer`, `DPOTrainer`, `GRPOTrainer`, etc.) with minimal setup. Ensure you have the latest version of `trl` installed (version 1.2.0 or higher).

```python
from datasets import Dataset
from trl import SFTConfig, SFTTrainer

# Create a small fake dataset
prompts = ["The capital of France is", "Hamlet was written by"] * 12
completions = [" Paris.", " Shakespeare."] * 12
dataset = Dataset.from_dict({"prompt": prompts, "completion": completions})

# Train a model using the TRL SFTTrainer API
trainer = SFTTrainer(
    model="Qwen/Qwen3-0.6B",
    args=SFTConfig(report_to="trackio", run_name="Qwen3-0.6B-sft"),
    train_dataset=dataset,
)
trainer.train()
```

## Configuring Project and Space

Set the project and space ID directly in your TRL config (e.g. [`~trl.SFTConfig`], [`~trl.DPOConfig`], [`~trl.GRPOConfig`]):

```python
from trl import SFTConfig

args = SFTConfig(
    report_to="trackio",
    run_name="my-run",
    project="my-project",
    trackio_space_id="username/space_id",
)
```

