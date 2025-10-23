import random
import time

import numpy as np

import trackio

PROJECT_ID = random.randint(100000, 999999)
NUM_RUNS = 3
NUM_STEPS = 20


def train_model(run_id):
    """Simulate training with histograms for a single run"""
    trackio.init(
        project=f"histogram-demo-{PROJECT_ID}",
        name=f"run-{run_id}",
        config={
            "learning_rate": 0.001 * (run_id + 1),
            "batch_size": 32 * (run_id + 1),
        },
        space_id=f"histogram-test-{PROJECT_ID}",
    )

    for step in range(NUM_STEPS):
        # Simulate loss decreasing over time
        loss = 1.0 * np.exp(-step * 0.1) + np.random.normal(0, 0.05)

        # Simulate accuracy increasing over time
        accuracy = min(0.95, 0.5 + step * 0.02 + np.random.normal(0, 0.02))

        # Create weight distribution that gets tighter over time
        weight_std = 0.5 * np.exp(-step * 0.05)
        weights = np.random.normal(0, weight_std, 100)

        # Create gradient distribution that changes over time
        gradient_scale = 0.1 * np.exp(-step * 0.03)
        gradients = np.random.laplace(0, gradient_scale, 100)

        # Log scalar metrics and histograms
        trackio.log(
            {
                "loss": loss,
                "accuracy": accuracy,
                "weight_distribution": trackio.Histogram(weights, num_bins=20),
                "gradient_distribution": trackio.Histogram(gradients, num_bins=20),
            },
            step=step,
        )

        time.sleep(0.1)  # Small delay between steps

    trackio.finish()


# Run multiple training runs
for run_id in range(NUM_RUNS):
    print(f"Starting run {run_id + 1}/{NUM_RUNS}")
    train_model(run_id)
    print(f"Completed run {run_id + 1}/{NUM_RUNS}")

print(f"\nAll {NUM_RUNS} runs completed!")
print(f"Run 'trackio show --project histogram-demo-{PROJECT_ID}' to view the results")
