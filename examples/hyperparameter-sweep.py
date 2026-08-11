import random
import time

import trackio as wandb


def main():
    project_id = random.randint(10000, 99999)
    project_name = f"sweep-demo-{project_id}"
    steps = 10

    def train():
        run = wandb.init(project=project_name)
        lr = run.config["learning_rate"]
        batch_size = run.config["batch_size"]

        performance_factor = (1.0 / (lr * 100)) * (32 / batch_size)
        base_loss = random.uniform(1.2, 1.8) / performance_factor
        min_loss = random.uniform(0.05, 0.12) / performance_factor

        for step in range(steps):
            progress = step / (steps - 1)
            loss = base_loss * (1.0 - 0.85 * progress) + random.uniform(-0.03, 0.03)
            loss = max(min_loss, loss)
            wandb.log({"loss": round(loss, 4)}, step=step)
            time.sleep(0.05)

        wandb.finish()

    wandb.sweep(
        {
            "method": "grid",
            "name": f"{project_name}-sweep",
            "parameters": {
                "learning_rate": {"values": [1e-2, 1e-3, 1e-4]},
                "batch_size": {"values": [16, 32, 64]},
            },
        },
        function=train,
    )

    print(f"\nDone! View the sweep with: trackio show --project {project_name}")


if __name__ == "__main__":
    main()
