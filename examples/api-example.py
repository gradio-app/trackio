import trackio
from trackio import Api

project = "api_example_project"

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

api = Api()
runs = api.runs(project)
runs[0].delete()
