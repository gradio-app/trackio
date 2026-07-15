"""Populate the artifacts UI with a small multi-run pipeline, then launch it.

Runs a data-prep -> train -> evaluate pipeline that logs three artifact types
(dataset, model, report) across several versions and runs, then opens the
dashboard. Things to look at in the UI:

- Artifacts tab: the sidebar groups artifacts by type; each version shows its
  aliases, files, size, digest, nested metadata, and the runs that used it.
- Run pages: `prepare-data` lists the dataset under "Output artifacts", the
  train runs list it under "Input artifacts", and `evaluate` links both the
  best model (input) and the eval report (output).

Usage:
    python examples/artifacts-ui-demo.py
"""

import json
import random
import tempfile
from pathlib import Path

import trackio

PROJECT = f"artifacts-ui-demo-{random.randint(100000, 999999)}"
EPOCHS = 5
LEARNING_RATES = [0.01, 0.001]


def write_dataset(directory: Path, version: int, rows: int) -> None:
    """Write fake train/val CSV splits and a dataset card to `directory`."""
    header = "text,label\n"
    row = "this movie was {sentiment},{label}\n"
    train = header + "".join(
        row.format(sentiment=random.choice(["great", "terrible"]), label=i % 2)
        for i in range(rows)
    )
    val = header + "".join(
        row.format(sentiment=random.choice(["great", "terrible"]), label=i % 2)
        for i in range(rows // 5)
    )
    (directory / "train.csv").write_text(train)
    (directory / "val.csv").write_text(val)
    (directory / "README.md").write_text(
        f"# Movie reviews (v{version})\n\nTiny fake sentiment dataset.\n"
    )


def write_checkpoint(directory: Path, lr: float, loss: float) -> None:
    """Write a tiny fake model checkpoint and its config to `directory`."""
    (directory / "config.json").write_text(
        json.dumps({"hidden_size": 128, "num_layers": 2, "lr": lr}, indent=2)
    )
    (directory / "weights.bin").write_bytes(
        random.randbytes(2048) + f"loss={loss:.4f}".encode()
    )


def fake_loss(epoch: int, lr: float) -> float:
    """Generate a decreasing loss where the smaller learning rate wins."""
    base = 2.0 * (0.6 if lr < 0.005 else 0.75) ** epoch
    return max(0.05, base + random.gauss(0, 0.05))


def prepare_data(tmp: Path) -> None:
    trackio.init(project=PROJECT, name="prepare-data")
    for version, rows in enumerate([50, 200]):
        data_dir = tmp / f"dataset-v{version}"
        data_dir.mkdir()
        write_dataset(data_dir, version, rows)

        artifact = trackio.Artifact(
            name="movie-reviews",
            type="dataset",
            description=f"Fake sentiment dataset with {rows} training rows",
            metadata={
                "rows": {"train": rows, "val": rows // 5},
                "source": "synthetic",
                "schema": {"columns": ["text", "label"], "label_type": "binary"},
            },
        )
        artifact.add_dir(data_dir)
        aliases = ["full"] if version == 1 else None
        logged = trackio.log_artifact(artifact, aliases=aliases)
        print(f"prepare-data: logged {logged.qualified_name}")
    trackio.finish()


def train(lr: float, best_loss: float) -> float:
    trackio.init(project=PROJECT, name=f"train-lr-{lr}", config=dict(lr=lr))
    dataset = trackio.use_artifact("movie-reviews:full", type="dataset")
    print(f"train-lr-{lr}: using {dataset.qualified_name}")

    loss = float("inf")
    for epoch in range(EPOCHS):
        loss = fake_loss(epoch, lr)
        trackio.log({"train/loss": round(loss, 4)}, step=epoch)

    with tempfile.TemporaryDirectory() as ckpt_tmp:
        ckpt_dir = Path(ckpt_tmp) / "checkpoint"
        ckpt_dir.mkdir()
        write_checkpoint(ckpt_dir, lr, loss)

        artifact = trackio.Artifact(
            name="sentiment-model",
            type="model",
            description=f"Model trained with lr={lr}",
            metadata={
                "final_loss": round(loss, 4),
                "hyperparameters": {"lr": lr, "epochs": EPOCHS},
                "dataset": dataset.qualified_name,
            },
        )
        artifact.add_dir(ckpt_dir)
        aliases = ["best"] if loss < best_loss else None
        logged = trackio.log_artifact(artifact, aliases=aliases)
        print(f"train-lr-{lr}: logged {logged.qualified_name} (loss={loss:.4f})")

    trackio.finish()
    return loss


def evaluate(tmp: Path) -> None:
    trackio.init(project=PROJECT, name="evaluate")
    model = trackio.use_artifact("sentiment-model:best", type="model")
    dataset = trackio.use_artifact("movie-reviews:full", type="dataset")
    print(f"evaluate: using {model.qualified_name} and {dataset.qualified_name}")

    model_dir = Path(model.download())
    config = json.loads((model_dir / "config.json").read_text())
    accuracy = round(random.uniform(0.85, 0.95), 4)
    trackio.log({"eval/accuracy": accuracy})

    report_dir = tmp / "report"
    report_dir.mkdir()
    (report_dir / "metrics.json").write_text(
        json.dumps({"accuracy": accuracy, "model_config": config}, indent=2)
    )
    (report_dir / "report.md").write_text(
        f"# Evaluation report\n\nEvaluated `{model.qualified_name}` "
        f"on `{dataset.qualified_name}`: accuracy {accuracy}.\n"
    )

    artifact = trackio.Artifact(
        name="eval-report",
        type="report",
        description="Evaluation of the best sentiment model",
        metadata={"accuracy": accuracy, "model": model.qualified_name},
    )
    artifact.add_dir(report_dir)
    logged = trackio.log_artifact(artifact, aliases=["latest-eval"])
    print(f"evaluate: logged {logged.qualified_name}")
    trackio.finish()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        prepare_data(tmp)

        best_loss = float("inf")
        for lr in LEARNING_RATES:
            best_loss = min(best_loss, train(lr, best_loss))

        evaluate(tmp)

    print(f"\nOpen the Artifacts tab for project {PROJECT} to explore the results.")
    trackio.show(project=PROJECT)


if __name__ == "__main__":
    main()
