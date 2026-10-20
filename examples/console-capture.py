import logging
import math
import random
import sys
import time

import trackio

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("train")

PROJECT = "console-capture-demo"
STEPS = 30

trackio.init(
    project=PROJECT,
    name="with-console-capture",
    config={"lr": 3e-4, "batch_size": 32, "steps": STEPS},
    capture_console=True,
)

print(f"Starting training for {STEPS} steps")
for step in range(STEPS):
    loss = 2.0 * math.exp(-step / 10) + random.uniform(0, 0.05)
    logger.info("step %d/%d loss=%.4f", step + 1, STEPS, loss)
    for pct in (25, 50, 75, 100):
        sys.stderr.write(f"\rbatch progress: {pct:3d}%")
        sys.stderr.flush()
    sys.stderr.write("\n")
    if step == STEPS // 2:
        logger.warning("Loss plateau detected, lowering learning rate")
    trackio.log({"loss": loss})
    time.sleep(0.5)
print("Training complete")
trackio.finish()

trackio.init(
    project=PROJECT,
    name="without-console-capture",
    config={"lr": 3e-4, "batch_size": 32, "steps": 5},
)
for step in range(5):
    print(f"step {step}: this output is not captured")
    trackio.log({"loss": 1.0 / (step + 1)})
trackio.finish()

print(f'View both runs on the Runs page: trackio show --project "{PROJECT}"')
