import random
import time

import trackio

PROJECT_ID = random.randint(100000, 999999)
PROJECT_NAME = f"report-demo-{PROJECT_ID}"

trackio.init(
    project=PROJECT_NAME,
    name="run-with-report",
    config={"epochs": 12, "learning_rate": 0.001},
)

loss_values = []
accuracy_values = []

for step in range(12):
    loss = round(1.2 / (step + 1) + random.uniform(-0.03, 0.03), 4)
    accuracy = round(min(0.98, 0.5 + step * 0.04 + random.uniform(-0.02, 0.02)), 4)
    loss_values.append(loss)
    accuracy_values.append(accuracy)

    trackio.log(
        {
            "train/loss": loss,
            "train/accuracy": accuracy,
        },
        step=step,
    )
    time.sleep(0.1)

best_accuracy = max(accuracy_values)
final_loss = loss_values[-1]
final_accuracy = accuracy_values[-1]

report_md = f"""# Training Report

Training completed for `{PROJECT_NAME}`.

## Final Metrics

- Final loss: `{final_loss}`
- Final accuracy: `{final_accuracy}`
- Best accuracy: `{best_accuracy}`
"""

trackio.log({"training_report": trackio.Markdown(report_md)})
trackio.finish()

print(f"Run complete. Open with: trackio show --project {PROJECT_NAME}")
