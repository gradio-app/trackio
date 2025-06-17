import math
import random
import time

import trackio as wandb

EPOCHS = 20
PROJECT_ID = random.randint(100000, 999999)


def generate_loss_curve(epoch, max_epochs, base_loss=2.5, min_loss=0.1):
    """Generate a realistic loss curve that decreases over time with noise"""
    progress = epoch / max_epochs
    base_curve = base_loss * math.exp(-3 * progress) + min_loss

    noise_scale = 0.3 * (1 - progress * 0.7)
    noise = random.gauss(0, noise_scale)

    return max(min_loss * 0.5, base_curve + noise)


def generate_accuracy_curve(epoch, max_epochs, max_acc=0.95, min_acc=0.1):
    """Generate a realistic accuracy curve that increases over time with noise"""
    progress = epoch / max_epochs
    base_curve = max_acc / (1 + math.exp(-6 * (progress - 0.5))) + min_acc

    noise_scale = 0.08 * (1 - progress * 0.5)
    noise = random.gauss(0, noise_scale)

    return max(0, min(max_acc, base_curve + noise))


for run in range(3):
    wandb.init(
        project=f"fake-training-{PROJECT_ID}",
        name=f"test-run-{run}",
        config=dict(
            epochs=EPOCHS,
            learning_rate=0.001,
            batch_size=32,
        ),
    )

    for epoch in range(EPOCHS):
        train_loss = generate_loss_curve(
            epoch,
            EPOCHS,
            base_loss=random.uniform(2.5, 3.5),
            min_loss=random.uniform(0.05, 0.15),
        )
        val_loss = generate_loss_curve(
            epoch,
            EPOCHS,
            base_loss=random.uniform(2.5, 3.5),
            min_loss=random.uniform(0.05, 0.15),
        )

        train_accuracy = generate_accuracy_curve(
            epoch,
            EPOCHS,
            max_acc=random.uniform(0.7, 0.9),
            min_acc=random.uniform(0.1, 0.3),
        )
        val_accuracy = generate_accuracy_curve(
            epoch,
            EPOCHS,
            max_acc=random.uniform(0.7, 0.9),
            min_acc=random.uniform(0.1, 0.3),
        )

        if epoch > 2 and random.random() < 0.3:
            val_loss *= 1.1
            val_accuracy *= 0.95

        wandb.log(
            {
                "train_loss": round(train_loss, 4),
                "train_accuracy": round(train_accuracy, 4),
                "val_loss": round(val_loss, 4),
                "val_accuracy": round(val_accuracy, 4),
            }
        )

        time.sleep(1)

    wandb.finish()
