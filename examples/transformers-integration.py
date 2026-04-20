# /// script
# dependencies = [
#   "trackio>=0.21.1",
#   "datasets>=4.4.0",
#   "transformers[torch]>=5.0.0rc2",
#   "huggingface_hub>=1.0.0",
# ]
# ///

import random

import huggingface_hub
from datasets import Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

suffix = random.randint(100000, 999999)
model_name = "distilbert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)

texts = ["Positive", "Negative", "Good", "Bad", "Great", "Poor"] * 3
labels = [1, 0, 1, 0, 1, 0] * 3

encodings = tokenizer(texts, truncation=True, padding=True, max_length=64)
dataset = Dataset.from_dict({**encodings, "labels": labels})

username = huggingface_hub.whoami(cache=True)["name"]
hub_model_id = f"{username}/trackio-transformers-demo-{suffix}"

# Local Trackio logs by default; the first Hub push runs sync(sdk="static") and links the dashboard on the model card.

trainer = Trainer(
    model=model,
    args=TrainingArguments(
        output_dir="./model_output",
        num_train_epochs=1,
        per_device_train_batch_size=4,
        learning_rate=2e-5,
        logging_steps=1,
        report_to="trackio",
        project=f"trackio-transformers-demo-{suffix}",
        push_to_hub=bool(hub_model_id),
        hub_model_id=hub_model_id,
    ),
    train_dataset=dataset,
)

trainer.train()
trainer.push_to_hub()

print(f"Model pushed to Hub, available at: https://huggingface.co/{hub_model_id}")
