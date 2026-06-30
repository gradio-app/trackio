import json
import random
import tempfile
from pathlib import Path

import trackio as wandb

LOSSES = [2.5, 1.2, 0.4, 0.7, 0.9]
EPOCHS = len(LOSSES)
PROJECT = f"artifacts-demo-{random.randint(100000, 999999)}"


def write_checkpoint(directory: Path, epoch: int, loss: float) -> None:
    """Write a tiny fake model checkpoint and its config to `directory`."""
    (directory / "config.json").write_text(
        json.dumps({"hidden_size": 256, "num_layers": 4, "epoch": epoch}, indent=2)
    )
    (directory / "weights.bin").write_bytes(
        random.randbytes(1024) + f"loss={loss:.4f}".encode()
    )


wandb.init(project=PROJECT, name="train", config=dict(epochs=EPOCHS))

with tempfile.TemporaryDirectory() as tmp:
    ckpt_dir = Path(tmp) / "checkpoint"

    best_loss = float("inf")
    for epoch, loss in enumerate(LOSSES):
        wandb.log({"train/loss": round(loss, 4)}, step=epoch)

        ckpt_dir.mkdir(exist_ok=True)
        write_checkpoint(ckpt_dir, epoch, loss)

        artifact = wandb.Artifact(
            name="model",
            type="model",
            description=f"Checkpoint after epoch {epoch}",
            metadata={"epoch": epoch, "loss": loss},
        )
        artifact.add_dir(ckpt_dir)

        aliases = ["best"] if loss < best_loss else None
        if loss < best_loss:
            best_loss = loss

        logged = wandb.log_artifact(artifact, aliases=aliases)
        print(
            f"epoch {epoch}: logged {logged.qualified_name} "
            f"(aliases={list(logged.aliases)}, size={logged.size} bytes)"
        )

wandb.finish()


wandb.init(project=PROJECT, name="evaluate")

best = wandb.use_artifact("model:best", type="model")
print(f"\nResolved 'model:best' -> {best.qualified_name}")
print(f"Description: {best.description}")
print(f"Metadata:    {best.metadata}")

local_dir = best.download()
print(f"\nDownloaded {len(best.manifest)} file(s) to {local_dir}:")
for entry in best.manifest:
    print(f"  - {entry['path']} ({entry['size']} bytes)")

config = json.loads((Path(local_dir) / "config.json").read_text())
print(f"\nLoaded config from downloaded checkpoint: {config}")

wandb.finish()
