"""Small deterministic training-like workload with no framework integration.

The script reads an input fixture, records metrics, writes a model-like output,
and emits stdout and stderr using only the Python standard library.
"""

import json
import sys
from pathlib import Path

INPUT_PATH = Path("examples/files/generic-training-demo.json")
OUTPUT_DIR = Path("artifacts/generic-training-demo")


def main() -> None:
    dataset = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    epochs = dataset["epochs"]
    learning_rate = dataset["learning_rate"]

    print(f"Loaded {len(dataset['examples'])} examples from {INPUT_PATH}")
    metrics = []
    for epoch in range(epochs):
        progress = (epoch + 1) / epochs
        loss = round(1.4 * (1 - progress) ** 2 + 0.08, 4)
        accuracy = round(0.52 + 0.43 * progress, 4)
        metrics.append({"epoch": epoch + 1, "loss": loss, "accuracy": accuracy})
        print(f"epoch={epoch + 1}/{epochs} loss={loss:.4f} accuracy={accuracy:.4f}")
        if epoch == 1:
            print(
                "diagnostic: validation metrics are now being recorded",
                file=sys.stderr,
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = OUTPUT_DIR / "model.snapshot"
    metrics_path = OUTPUT_DIR / "training.metrics"
    report_path = OUTPUT_DIR / "evaluation.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "format": "generic-training-demo",
                "weights": [
                    round(learning_rate * (index + 1) * accuracy, 6)
                    for index in range(3)
                ],
                "source_examples": len(dataset["examples"]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    metrics_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in metrics) + "\n",
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

    print(f"Wrote arbitrary-extension output: {snapshot_path}")
    print(f"Wrote metric history: {metrics_path}")
    print(f"Wrote evaluation report: {report_path}")


if __name__ == "__main__":
    main()
