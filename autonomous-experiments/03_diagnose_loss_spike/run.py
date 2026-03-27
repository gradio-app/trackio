import math
import random

import trackio as wandb

STEPS = 12000
SPIKE_STEP = 8000


# LR schedule: warmup, then a bump at SPIKE_STEP
def get_learning_rate(step):
    if step < 1000:
        return 1e-4 * (step / 1000)  # linear warmup
    elif step < SPIKE_STEP:
        return 1e-4
    elif step < SPIKE_STEP + 50:
        # Sudden bump — simulates a bad schedule or bug
        return 4e-4
    else:
        # Slowly recover
        steps_after = step - (SPIKE_STEP + 50)
        return max(1e-4, 4e-4 * math.exp(-steps_after / 500))


# Weight norm drifts upward slowly before the spike
def get_weight_norm(step):
    base = 2.0 + (step / STEPS) * 4.0  # slow drift from 2 -> 6
    noise = random.gauss(0, 0.05)
    if step >= SPIKE_STEP and step < SPIKE_STEP + 200:
        # Norms jump when gradients explode
        surge = 8.0 * math.exp(-(step - SPIKE_STEP) / 80)
        return base + surge + noise
    return base + noise


# Gradient norm is stable, then explodes at spike, then recovers
def get_grad_norm(step):
    if step < SPIKE_STEP:
        base = 1.0 + random.gauss(0, 0.1)
        return max(0.1, base)
    elif step < SPIKE_STEP + 30:
        # Explosion
        peak = 500.0 * math.exp(-(step - SPIKE_STEP) / 15)
        return peak + random.gauss(0, 10)
    else:
        # Gradual recovery
        steps_after = step - (SPIKE_STEP + 30)
        base = 1.0 + 20.0 * math.exp(-steps_after / 300)
        return max(0.1, base + random.gauss(0, 0.2))


# Loss decreases smoothly, spikes at SPIKE_STEP, then recovers
def get_loss(step):
    # Healthy decreasing curve
    progress = min(step, SPIKE_STEP) / SPIKE_STEP
    healthy_loss = 2.5 * math.exp(-3 * progress) + 0.1
    noise = random.gauss(0, 0.02)

    if step < SPIKE_STEP:
        return max(0.05, healthy_loss + noise)
    elif step < SPIKE_STEP + 50:
        # Spike
        spike_magnitude = 3.5 * math.exp(-(step - SPIKE_STEP) / 20)
        return healthy_loss + spike_magnitude + abs(noise)
    else:
        # Recover, but lands slightly worse than pre-spike
        steps_after = step - (SPIKE_STEP + 50)
        recovery_loss = (healthy_loss + 0.3) * math.exp(-steps_after / 800) + 0.15
        return max(0.1, recovery_loss + noise)


wandb.init(
    project="spike-demo",
    name="run-0",
    config=dict(
        total_steps=STEPS,
        spike_step=SPIKE_STEP,
        base_lr=1e-4,
        spike_lr=4e-4,
    ),
)

for step in range(STEPS):
    lr = get_learning_rate(step)
    weight_norm = get_weight_norm(step)
    grad_norm = get_grad_norm(step)
    loss = get_loss(step)

    wandb.log(
        {
            "train/loss": round(loss, 4),
            "train/grad_norm": round(grad_norm, 4),
            "train/weight_norm": round(weight_norm, 4),
            "train/learning_rate": lr,
        },
        step=step,
    )

wandb.finish()
