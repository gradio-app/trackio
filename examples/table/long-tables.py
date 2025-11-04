#!/usr/bin/env python3
"""
Example: Logging Tables with Images

This example demonstrates the capability to include trackio.Image objects
in trackio.Table columns. The images will be displayed as thumbnails in the
dashboard with captions as alt text.

Run with: python examples/table/table-with-images.py
"""

import random

import numpy as np
import pandas as pd

import trackio


def create_long_text(num_sentences: int = 100):
    text = ""
    for i in range(num_sentences):
        text += f"This is a long text that will be displayed in the table (sentence {i}). "
    return text


def main():
    trackio.init(
        project=f"table-with-long-text-{random.randint(0, 1000000)}",
        name="sample-run",
    )

    data = {
        "experiment_id": [1, 2, 3, 4],
        "model_type": ["CNN", "ResNet", "VGG", "Custom"],
        "accuracy": [0.85, 0.92, 0.88, 0.95],
        "loss": [0.15, 0.08, 0.12, 0.05],
        "notes": [create_long_text(1), create_long_text(5), create_long_text(10), create_long_text(20)],
    }

    df = pd.DataFrame(data)
    table = trackio.Table(dataframe=df)

    trackio.log({"experiment_results": table})

    for step in range(10):
        trackio.log(
            {
                "training_loss": 1.0 * np.exp(-step * 0.1) + 0.1,
                "validation_accuracy": 0.5 + 0.4 * (1 - np.exp(-step * 0.15)),
                "learning_rate": 0.001 * (0.95**step),
            },
            step=step,
        )

    trackio.finish()


if __name__ == "__main__":
    main()
