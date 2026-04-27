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
    "What is the capital of France?",
    "Who wrote Hamlet?",
    "What is 2 + 2?",
    "What color is the sky?",
    "Name a primary color.",
    "What is the largest planet?",
] * 4
completions = [
    "Paris.",
    "Shakespeare.",
    "4.",
    "Blue.",
    "Red.",
    "Jupiter.",
] * 4
dataset = Dataset.from_dict({"prompt": prompts, "completion": completions})

trainer = SFTTrainer(
    model="trl-internal-testing/tiny-LlamaForCausalLM-3",
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
