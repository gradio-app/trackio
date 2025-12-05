import random
import time

import trackio as wandb

PROJECT_ID = random.randint(100000, 999999)
EPOCHS = 10


def main():
    wandb.init(
        project=f"test-save-{PROJECT_ID}",
        name="test-run",
        config={
            "epochs": EPOCHS,
            "learning_rate": 0.001,
            "batch_size": 32,
        },
    )

    wandb.save("files/config1.yml")
    wandb.save("files/config2.yml")
    wandb.save("files/models/*.pth")

    for epoch in range(EPOCHS):
        loss = 2.0 * (1 - epoch / EPOCHS) + random.uniform(-0.1, 0.1)
        accuracy = 0.5 + 0.4 * (epoch / EPOCHS) + random.uniform(-0.05, 0.05)

        wandb.log(
            {
                "loss": round(loss, 4),
                "accuracy": round(accuracy, 4),
            }
        )

        time.sleep(0.1)

    wandb.finish()
    print(f"* Test completed. Check project 'test-save-{PROJECT_ID}' for saved files.")


if __name__ == "__main__":
    main()

