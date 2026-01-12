import trackio
from trackio import Api

project = "api_example_project"

print("Creating multiple training runs...")

for i in range(3):
    run_name = f"training_run_{i}"
    trackio.init(project=project, name=run_name)

    for step in range(5):
        trackio.log(
            {
                "loss": 1.0 / (step + 1),
                "accuracy": 0.5 + step * 0.1,
            }
        )

    trackio.finish()
    print(f"  Created run: {run_name}")

print(f"\nAll runs in '{project}':")
api = Api()
runs = api.runs(project)
for run in runs:
    print(f"  - {run.name}")

print(f"\nDeleting run: {runs[0].name}")
runs[0].delete()

print(f"\nRemaining runs in '{project}':")
runs = api.runs(project)
for run in runs:
    print(f"  - {run.name}")

print(f"\nTotal runs remaining: {len(runs)}")
