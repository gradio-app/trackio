# /// script
# dependencies = [
#   "trackio>=0.23.0",
#   "trl>=1.2.0",
#   "datasets>=4.4.0",
#   "transformers[torch]>=5.0.0rc2",
#   "huggingface_hub>=1.0.0",
# ]
# ///

import random

from datasets import Dataset
from trl import SFTConfig, SFTTrainer

suffix = random.randint(100000, 999999)
project_name = f"trackio-trl-demo-{suffix}"

prompts = [
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "user", "content": "Who wrote Hamlet?"},
    {"role": "user", "content": "What is 2 + 2?"},
    {"role": "user", "content": "What color is the sky?"},
    {"role": "user", "content": "Name a primary color."},
    {"role": "user", "content": "What is the largest planet?"},
] * 4
completions = [
    {"role": "assistant", "content": "Paris."},
    {"role": "assistant", "content": "Shakespeare."},
    {"role": "assistant", "content": "4."},
    {"role": "assistant", "content": "Blue."},
    {"role": "assistant", "content": "Red."},
    {"role": "assistant", "content": "Jupiter."},
] * 4
dataset = Dataset.from_dict({"prompt": prompts, "completion": completions})

trainer = SFTTrainer(
    model="Qwen/Qwen3-0.6B",
    args=SFTConfig(
        output_dir="./model_output",
        num_train_epochs=1,
        per_device_train_batch_size=4,
        learning_rate=2e-5,
        logging_steps=1,
        report_to="trackio",
        project=project_name,
    ),
    train_dataset=dataset,
)

trainer.train()

print(f"Run complete. Open with: trackio show --project {project_name}")
