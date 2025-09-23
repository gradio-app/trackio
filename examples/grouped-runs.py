import random
import time

import trackio as wandb


def main():
    project_id = random.randint(10000, 99999)
    project_name = f"grouped-runs-demo-{project_id}"

    groups = [
        ("baseline", 0.9),
        ("augmented", 1.0),
        ("tuned", 1.15),
    ]

    num_runs_per_group = 2
    steps = 12

    for group_name, performance_factor in groups:
        for run_index in range(1, num_runs_per_group + 1):
            run_name = f"{group_name}-run-{run_index}"
            wandb.init(
                project=project_name,
                name=run_name,
                group=group_name,
                config={
                    "learning_rate": random.choice([1e-3, 5e-4, 2e-4]),
                    "batch_size": random.choice([16, 32, 64]),
                },
            )

            base_loss = random.uniform(1.2, 1.8) / performance_factor
            min_loss = random.uniform(0.05, 0.12) / performance_factor

            for step in range(steps):
                progress = step / (steps - 1)
                loss = base_loss * (1.0 - 0.85 * progress) + random.uniform(-0.03, 0.03)
                loss = max(min_loss, loss)

                accuracy = (
                    0.5
                    + 0.45 * progress * performance_factor
                    + random.uniform(-0.02, 0.02)
                )
                accuracy = max(0.0, min(0.99, accuracy))

                wandb.log(
                    {
                        "loss": round(loss, 4),
                        "accuracy": round(accuracy, 4),
                    },
                    step=step,
                )

                time.sleep(0.05)

            wandb.finish()


if __name__ == "__main__":
    main()
