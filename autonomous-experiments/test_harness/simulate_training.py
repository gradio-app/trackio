"""
Synthetic training simulator for testing autonomous ML workflows with Trackio.

Simulates realistic training curves parameterized by hyperparameters.
No ML framework dependencies - runs in seconds on CPU.

Usage:
    python simulate_training.py --project my_exp --run-name lr-0.01 --steps 500 --lr 0.01
    python simulate_training.py --project my_exp --run-name spike-test --steps 500 --lr 0.01 --spike-at-step 300
"""

import argparse
import math
import random
import sys
import time

import trackio
from trackio.alerts import AlertLevel

NOISE_SCALE = 0.05


def simulate_loss(step, total_steps, lr, depth, batch_size, base_loss=3.0):
    convergence_rate = 2.0 / (1.0 + lr * 100)
    if lr > 0.5:
        convergence_rate = -0.5

    depth_factor = min(depth / 6.0, 2.0)
    batch_factor = 1.0 + 0.1 * math.log2(max(batch_size, 1) / 32)

    progress = step / max(total_steps, 1)
    base = base_loss * math.exp(
        -convergence_rate * depth_factor * batch_factor * progress * 5
    )
    noise = random.gauss(0, NOISE_SCALE * (1 - progress * 0.5))

    if lr > 0.1:
        oscillation = 0.3 * lr * math.sin(step * lr * 0.5)
        base += abs(oscillation)

    if lr > 1.0 and step > 50:
        base += lr * step * 0.001

    return max(0.01, base + noise)


def simulate_val_loss(train_loss, step, total_steps, depth, overfitting_threshold=0.6):
    progress = step / max(total_steps, 1)
    gap = 0.05

    if progress > overfitting_threshold and depth > 8:
        overfit_amount = (progress - overfitting_threshold) * depth * 0.05
        gap += overfit_amount

    noise = random.gauss(0, 0.02)
    return train_loss + gap + noise


def simulate_accuracy(loss):
    return max(0, min(1, 1 - loss / 3.0 + random.gauss(0, 0.01)))


def main():
    parser = argparse.ArgumentParser(description="Synthetic training simulator")
    parser.add_argument("--project", required=True, help="Trackio project name")
    parser.add_argument("--run-name", required=True, help="Run name")
    parser.add_argument("--steps", type=int, default=500, help="Total training steps")
    parser.add_argument("--lr", type=float, default=0.01, help="Learning rate")
    parser.add_argument("--depth", type=int, default=6, help="Model depth (layers)")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument(
        "--spike-at-step", type=int, default=None, help="Simulate loss spike at step N"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Sleep between steps (simulate wall-clock time)",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    config = {
        "lr": args.lr,
        "depth": args.depth,
        "batch_size": args.batch_size,
        "steps": args.steps,
    }

    trackio.init(project=args.project, name=args.run_name, config=config)

    best_val_loss = float("inf")
    stagnation_count = 0

    for step in range(args.steps):
        train_loss = simulate_loss(
            step, args.steps, args.lr, args.depth, args.batch_size
        )

        if args.spike_at_step and step == args.spike_at_step:
            train_loss *= 10.0
            trackio.alert(
                "Loss spike detected",
                text=f"Loss spiked to {train_loss:.4f} at step {step}",
                level=AlertLevel.WARN,
            )

        if math.isnan(train_loss) or math.isinf(train_loss):
            trackio.alert(
                "NaN/Inf loss detected",
                text=f"Loss became {train_loss} at step {step}. Training is diverging.",
                level=AlertLevel.ERROR,
            )
            trackio.log({"train/loss": train_loss, "val/loss": train_loss}, step=step)
            trackio.finish()
            print(f"TERMINATED EARLY: NaN/Inf loss at step {step}")
            sys.exit(1)

        val_loss = simulate_val_loss(train_loss, step, args.steps, args.depth)
        accuracy = simulate_accuracy(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            stagnation_count = 0
        else:
            stagnation_count += 1

        if train_loss > 10.0 and step > 50:
            trackio.alert(
                "Training diverging",
                text=f"Loss {train_loss:.4f} is very high at step {step}. Learning rate may be too high.",
                level=AlertLevel.ERROR,
            )
            trackio.log(
                {
                    "train/loss": round(train_loss, 4),
                    "val/loss": round(val_loss, 4),
                    "accuracy": round(accuracy, 4),
                    "best_val_loss": round(best_val_loss, 4),
                    "lr": args.lr,
                },
                step=step,
            )
            trackio.finish()
            print(f"TERMINATED EARLY: diverging at step {step}")
            sys.exit(1)

        if stagnation_count >= 100 and step > 100:
            trackio.alert(
                "Training stagnated",
                text=f"Val loss has not improved for {stagnation_count} steps. Best: {best_val_loss:.4f}",
                level=AlertLevel.WARN,
            )
            stagnation_count = 0

        if val_loss > train_loss * 1.5 and step > args.steps * 0.5:
            trackio.alert(
                "Overfitting detected",
                text=f"Val loss ({val_loss:.4f}) >> train loss ({train_loss:.4f}) at step {step}",
                level=AlertLevel.WARN,
            )

        trackio.log(
            {
                "train/loss": round(train_loss, 4),
                "val/loss": round(val_loss, 4),
                "accuracy": round(accuracy, 4),
                "best_val_loss": round(best_val_loss, 4),
                "lr": args.lr,
            },
            step=step,
        )

        if args.sleep > 0:
            time.sleep(args.sleep)

    trackio.alert(
        "Training complete",
        text=f"Finished {args.steps} steps. Best val loss: {best_val_loss:.4f}",
        level=AlertLevel.INFO,
    )
    trackio.finish()
    print(f"Training complete. Best val loss: {best_val_loss:.4f}")


if __name__ == "__main__":
    main()
