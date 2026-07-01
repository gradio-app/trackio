"""Artifact tracking against a deployed Hugging Face Space.

This mirrors `examples/artifacts.py` but passes `space_id` to `init`, so the
artifact blobs and metadata are uploaded to (and downloaded from) a real Space
instead of the local cache. After it runs, confirm the artifacts exist on the
Space with:

    trackio list artifacts --project <PROJECT> --space <SPACE_ID>
    trackio get artifact --project <PROJECT> --name model --version best --space <SPACE_ID>
"""

import json
import random
import tempfile
from pathlib import Path

import trackio as wandb

LOSSES = [2.5, 1.2, 0.4, 0.7, 0.9]
EPOCHS = len(LOSSES)
SUFFIX = random.randint(100000, 999999)
PROJECT = f"artifacts-demo-{SUFFIX}"
SPACE_ID = f"trackio-artifacts-{SUFFIX}"


def write_checkpoint(directory: Path, epoch: int, loss: float) -> None:
    """Write a tiny fake model checkpoint and its config to `directory`."""
    (directory / "config.json").write_text(
        json.dumps({"hidden_size": 256, "num_layers": 4, "epoch": epoch}, indent=2)
    )
    (directory / "weights.bin").write_bytes(
        random.randbytes(1024) + f"loss={loss:.4f}".encode()
    )


wandb.init(project=PROJECT, name="train", config=dict(epochs=EPOCHS), space_id=SPACE_ID)

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


wandb.init(project=PROJECT, name="evaluate", space_id=SPACE_ID)

best = wandb.use_artifact("model:best", type="model")
print(f"\nResolved 'model:best' -> {best.qualified_name}")
print(f"Description: {best.description}")
print(f"Metadata:    {best.metadata}")

local_dir = best.download()
print(f"\nDownloaded {len(best.manifest)} file(s) from the Space to {local_dir}:")
for entry in best.manifest:
    print(f"  - {entry['path']} ({entry['size']} bytes)")

config = json.loads((Path(local_dir) / "config.json").read_text())
print(f"\nLoaded config from downloaded checkpoint: {config}")

wandb.finish()


print("\nConfirm the artifacts on the Space with:")
print(f"  trackio list artifacts --project {PROJECT} --space {SPACE_ID}")
print(
    f"  trackio get artifact --project {PROJECT} --name model "
    f"--version best --space {SPACE_ID}"
)
