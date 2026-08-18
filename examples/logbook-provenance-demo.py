"""Small, deterministic workload for demonstrating Logbook provenance capture.

Run this from the repository root through ``trackio logbook run``. The script
intentionally reads an input fixture, writes an output with an arbitrary file
extension, emits stdout and stderr, logs metrics, and registers an artifact.
"""

import json
import sys
from pathlib import Path

import trackio

INPUT_PATH = Path("examples/files/logbook-provenance-demo.json")
OUTPUT_DIR = Path("artifacts/logbook-provenance-demo")


def main() -> None:
    dataset = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    epochs = dataset["epochs"]
    learning_rate = dataset["learning_rate"]

    trackio.init(
        project="logbook-provenance-demo",
        name="automatic-capture",
        config={
            "epochs": epochs,
            "learning_rate": learning_rate,
            "input": str(INPUT_PATH),
        },
    )

    print(f"Loaded {len(dataset['examples'])} examples from {INPUT_PATH}")
    for epoch in range(epochs):
        progress = (epoch + 1) / epochs
        loss = round(1.4 * (1 - progress) ** 2 + 0.08, 4)
        accuracy = round(0.52 + 0.43 * progress, 4)
        trackio.log({"train/loss": loss, "eval/accuracy": accuracy}, step=epoch)
        print(f"epoch={epoch + 1}/{epochs} loss={loss:.4f} accuracy={accuracy:.4f}")
        if epoch == 1:
            print(
                "diagnostic: validation metrics are now being recorded",
                file=sys.stderr,
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = OUTPUT_DIR / "model.snapshot"
    report_path = OUTPUT_DIR / "evaluation.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "format": "trackio-provenance-demo",
                "weights": [0.125, -0.25, 0.75],
                "source_examples": len(dataset["examples"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "accuracy": accuracy,
                "loss": loss,
                "input": str(INPUT_PATH),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    artifact = trackio.Artifact(
        name="demo-model",
        type="model",
        description="Tiny model produced by the Logbook provenance demo",
        metadata={"accuracy": accuracy, "epochs": epochs},
    )
    artifact.add_file(snapshot_path)
    artifact.add_file(report_path)
    logged = trackio.log_artifact(artifact, aliases=["latest", "demo"])

    print(f"Wrote arbitrary-extension output: {snapshot_path}")
    print(f"Logged semantic artifact: {logged.qualified_name}")
    trackio.finish()


if __name__ == "__main__":
    main()
