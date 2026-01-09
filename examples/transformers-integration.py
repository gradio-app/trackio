# /// script
# dependencies = [
#   "trackio>=0.14.2",
#   "datasets>=4.4.0",
#   "transformers[torch]>=5.0.0rc2",
#   "huggingface_hub>=1.0.0",
# ]
# ///

import os
from datasets import Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments
import huggingface_hub

model_name = "distilbert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)

texts = ["Positive", "Negative", "Good", "Bad", "Great", "Poor"] * 3
labels = [1, 0, 1, 0, 1, 0] * 3

encodings = tokenizer(texts, truncation=True, padding=True, max_length=64)
dataset = Dataset.from_dict({**encodings, "labels": labels})

username = huggingface_hub.whoami()["name"]
hub_model_id = f"{username}/trackio-transformers-demo"

os.environ["TRACKIO_PROJECT"] = "trackio-transformers-demo"

trainer = Trainer(
    model=model,
    args=TrainingArguments(
        output_dir="./model_output",
        num_train_epochs=1,
        per_device_train_batch_size=4,
        learning_rate=2e-5,
        logging_steps=1,
        report_to="trackio",
        push_to_hub=bool(hub_model_id),
        hub_model_id=hub_model_id,

    ),
    train_dataset=dataset,
)

trainer.train()
trainer.push_to_hub()

print(f"Model pushed to Hub, available at: https://huggingface.co/{hub_model_id}")

