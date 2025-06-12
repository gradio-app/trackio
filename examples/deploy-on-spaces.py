import random

from tqdm import tqdm

import trackio as wandb

project_id = random.randint(10000, 99999)

wandb.init(
    project=f"fake-training-{project_id}",
    name="test-run",
    config=dict(
        epochs=5,
        learning_rate=0.001,
        batch_size=32,
    ),
    space_id=f"abidlabs/trackio-{project_id}",
)

EPOCHS = 5
NUM_TRAIN_BATCHES = 100
NUM_VAL_BATCHES = 20

for epoch in range(EPOCHS):
    train_loss = 0
    train_accuracy = 0
    val_loss = 0
    val_accuracy = 0

    for _ in tqdm(range(NUM_TRAIN_BATCHES), desc=f"Epoch {epoch + 1} - Training"):
        loss = random.uniform(0.2, 1.0)
        accuracy = random.uniform(0.6, 0.95)
        train_loss += loss
        train_accuracy += accuracy

    for _ in tqdm(range(NUM_VAL_BATCHES), desc=f"Epoch {epoch + 1} - Validation"):
        loss = random.uniform(0.2, 0.9)
        accuracy = random.uniform(0.65, 0.98)
        val_loss += loss
        val_accuracy += accuracy

    train_loss /= NUM_TRAIN_BATCHES
    train_accuracy /= NUM_TRAIN_BATCHES
    val_loss /= NUM_VAL_BATCHES
    val_accuracy /= NUM_VAL_BATCHES

    wandb.log(
        {
            "train_loss": train_loss,
            "train_accuracy": train_accuracy,
            "val_loss": val_loss,
            "val_accuracy": val_accuracy,
        }
    )

wandb.finish()
