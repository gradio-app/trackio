# Generates a simple tfevents file for testing. Output is written to tf_test_run directory.

from pathlib import Path

from tensorboardX import SummaryWriter


def create_tfevents_tensorboardx(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    writer = SummaryWriter(log_dir=str(log_dir))

    for step in range(10):
        writer.add_scalar("loss", 1.0 / (step + 1), step)
        writer.add_scalar("accuracy", 0.8 + 0.02 * step, step)

    writer.close()


if __name__ == "__main__":
    create_tfevents_tensorboardx(Path("tf_test_run"))
    print("✅ .tfevents file written with tensorboardX")
