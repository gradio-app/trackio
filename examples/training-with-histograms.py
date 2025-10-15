import numpy as np

import trackio

run = trackio.init(project="histogram-training")

num_epochs = 10
batch_size = 32
learning_rate = 0.001

for epoch in range(num_epochs):
    epoch_losses = []
    epoch_weights = []

    for batch in range(20):
        loss = np.random.exponential(scale=2.0) * (1 - epoch * 0.05)
        epoch_losses.append(loss)

        weights = np.random.normal(0, 1 - epoch * 0.08, 1000)
        epoch_weights.extend(weights)

    avg_loss = np.mean(epoch_losses)

    trackio.log(
        {
            "loss": avg_loss,
            "learning_rate": learning_rate * (0.95**epoch),
            "loss_distribution": trackio.Histogram(epoch_losses, num_bins=20),
            "weight_distribution": trackio.Histogram(epoch_weights, num_bins=50),
        },
        step=epoch,
    )

gradients = np.random.laplace(0, 0.1, 5000)
trackio.log({"final_gradients": trackio.Histogram(gradients, num_bins=30)})

trackio.finish()
