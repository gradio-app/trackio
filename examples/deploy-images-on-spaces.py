import math
import random

import numpy as np
import pandas as pd
from PIL import Image

import trackio

EPOCHS = 20
PROJECT_ID = random.randint(100000, 999999)


def generate_loss(epoch, max_epochs, base_loss=2.5, min_loss=0.1):
    progress = epoch / max_epochs
    noise = random.gauss(0, 0.2 * (1 - progress * 0.7))
    return max(min_loss * 0.5, base_loss * math.exp(-3 * progress) + min_loss + noise)


def generate_accuracy(epoch, max_epochs, max_acc=0.95):
    progress = epoch / max_epochs
    noise = random.gauss(0, 0.05 * (1 - progress * 0.5))
    return max(0, min(max_acc, max_acc / (1 + math.exp(-6 * (progress - 0.5))) + noise))


def generate_sample_image(epoch, max_epochs, size=64):
    """Generate a gradient image that gets less noisy as training progresses."""
    progress = epoch / max_epochs
    x = np.linspace(0, 1, size)
    gradient = np.outer(x, x)
    channels = [
        gradient * 255 * (1 - progress),
        gradient.T * 255 * progress,
        np.full((size, size), 128),
    ]
    clean = np.stack(channels, axis=-1)
    noise = np.random.randint(0, 255, (size, size, 3)) * (1 - progress)
    pixels = np.clip(clean + noise * 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels)


trackio.init(
    project=f"deploy-images-on-spaces-{PROJECT_ID}",
    space_id=f"deploy-images-on-spaces-{PROJECT_ID}",
)

for epoch in range(EPOCHS):
    metrics = {
        "train_loss": round(generate_loss(epoch, EPOCHS), 4),
        "train_accuracy": round(generate_accuracy(epoch, EPOCHS), 4),
    }
    if epoch % 5 == 0 or epoch == EPOCHS - 1:
        metrics["sample"] = trackio.Image(
            generate_sample_image(epoch, EPOCHS),
            caption=f"Model output at epoch {epoch}",
        )
    trackio.log(metrics)

image = trackio.Image(
    Image.fromarray(np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8))
)
df = pd.DataFrame({"value": [0.1, 0.2, 0.3], "image": [[image, image], image, image]})
table = trackio.Table(dataframe=df)
trackio.log({"my_table": table})
trackio.finish()
